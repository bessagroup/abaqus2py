"""Tests for the supercompressible get_results post-processing.

Pure-synthetic coverage of the scalar formulas ported from the original
Bessa get_results (f3dasm history, commit 410eb18): sigma_crit, the
energy curve-qualification branches, NaN robustness for samples whose
upstream ABAQUS stages failed or were skipped, and the 3-class coilable
upgrade truth table. No ABAQUS or run data involved; the module under
test is resolved via the sys.path shim in conftest.py.
"""

import math

import numpy as np
import pytest
from f3dasm import ExperimentSample

from post_processing import (
    SupercompressiblePostProcessor,
    compute_energy,
    compute_sigma_crit,
    upgrade_coilable,
)

BOTTOM_DIAMETER = 100.0
BOTTOM_AREA = math.pi * BOTTOM_DIAMETER**2 / 4.0
RATIO_PITCH = 0.75
PITCH = RATIO_PITCH * BOTTOM_DIAMETER


def fields_from_curve(strain, stress):
    """Map a stress-strain curve back to the stored (3, n) U/RF arrays.

    Inverts the post-processor's strain = |U_3|/pitch and
    stress = |RF_3|/bottom_area * 1e3 relations; rows 0 and 1 (the
    non-axial directions) are zero-filled.
    """
    u3 = np.asarray(strain, dtype=float) * PITCH
    rf3 = np.asarray(stress, dtype=float) * BOTTOM_AREA / 1e3
    zeros = np.zeros_like(u3)
    return np.stack([zeros, zeros, u3]), np.stack([zeros, zeros, rf3])


def triangle_curve(
    peak_strain=0.1, peak_stress=10.0, end_strain=1.0, end_stress=0.0
):
    """Piecewise-linear rise-then-fall curve with a single local max."""
    strain_rise = np.linspace(0.0, peak_strain, 6)
    stress_rise = np.linspace(0.0, peak_stress, 6)
    strain_fall = np.arange(peak_strain + 0.02, end_strain + 1e-9, 0.02)
    slope = (end_stress - peak_stress) / (end_strain - peak_strain)
    stress_fall = peak_stress + (strain_fall - peak_strain) * slope
    strain = np.concatenate([strain_rise, strain_fall])
    stress = np.concatenate([stress_rise, stress_fall])
    return strain, stress


#                                                                    sigma_crit
# =============================================================================


def test_sigma_crit_formula():
    loads = np.array([10.0, 12.0, 13.0])
    expected = 10.0 / BOTTOM_AREA * 1e3  # = loads[0] * 0.12732...
    assert compute_sigma_crit(loads, BOTTOM_DIAMETER) == pytest.approx(
        expected
    )
    assert expected == pytest.approx(1.2732395, rel=1e-6)


@pytest.mark.parametrize(
    "loads",
    [None, [], np.array([]), float("nan"), [float("nan"), 2.0]],
)
def test_sigma_crit_missing_or_invalid_loads(loads):
    assert compute_sigma_crit(loads, BOTTOM_DIAMETER) is None


#                                                                        energy
# =============================================================================


def test_energy_qualifying_triangle():
    strain, stress = triangle_curve()
    U, RF = fields_from_curve(strain, stress)
    energy = compute_energy(U, RF, PITCH, BOTTOM_DIAMETER)
    # analytic triangle area = 1/2 * base * height; pchip only deviates
    # from linear near the kink at the peak.
    assert energy == pytest.approx(5.0, rel=0.02)


def test_energy_appends_endpoint_when_curve_stops_early():
    strain, stress = triangle_curve(end_strain=0.8, end_stress=2.0)
    U, RF = fields_from_curve(strain, stress)
    energy = compute_energy(U, RF, PITCH, BOTTOM_DIAMETER)
    # rise 0.5 + fall trapezoid 4.2 + appended (0.8,2.0)->(1.0,0.0) 0.2
    assert energy == pytest.approx(4.9, rel=0.05)


def test_energy_none_without_local_max():
    strain = np.linspace(0.0, 1.0, 30)
    stress = np.linspace(0.0, 10.0, 30)  # monotone: no softening branch
    U, RF = fields_from_curve(strain, stress)
    assert compute_energy(U, RF, PITCH, BOTTOM_DIAMETER) is None


def test_energy_none_with_insufficient_post_peak_strain():
    # peak at 0.5, curve ends at 0.53 < 0.5 + additional_strain_thresh
    strain_rise = np.linspace(0.0, 0.5, 6)
    stress_rise = np.linspace(0.0, 10.0, 6)
    strain_fall = np.array([0.51, 0.52, 0.53])
    stress_fall = np.array([8.0, 6.0, 4.0])
    U, RF = fields_from_curve(
        np.concatenate([strain_rise, strain_fall]),
        np.concatenate([stress_rise, stress_fall]),
    )
    assert compute_energy(U, RF, PITCH, BOTTOM_DIAMETER) is None


def test_energy_none_when_final_strain_too_large():
    strain, stress = triangle_curve(end_strain=1.15)
    U, RF = fields_from_curve(strain, stress)
    assert compute_energy(U, RF, PITCH, BOTTOM_DIAMETER) is None


def test_energy_none_on_non_recoverable_strain_reversal():
    # a backward jump larger than the -0.01 cleaning window
    strain = np.array([0.0, 0.2, 0.1, 0.3, 0.4])
    stress = np.array([0.0, 5.0, 4.0, 3.0, 2.0])
    U, RF = fields_from_curve(strain, stress)
    assert compute_energy(U, RF, PITCH, BOTTOM_DIAMETER) is None


def test_energy_cleans_small_strain_jitter():
    strain, stress = triangle_curve()
    # duplicate one point (diff == 0): must be cleaned, not fatal
    strain = np.insert(strain, 10, strain[9])
    stress = np.insert(stress, 10, stress[9])
    U, RF = fields_from_curve(strain, stress)
    energy = compute_energy(U, RF, PITCH, BOTTOM_DIAMETER)
    assert energy == pytest.approx(5.0, rel=0.02)


@pytest.mark.parametrize(
    "U, RF",
    [
        (None, None),
        (float("nan"), float("nan")),  # NaN column values, not arrays
        (np.full((3, 6), np.nan), np.full((3, 6), np.nan)),
        (np.zeros((3, 1)), np.zeros((3, 1))),  # single increment
        (None, np.zeros((3, 6))),
    ],
)
def test_energy_none_on_missing_or_nan_fields(U, RF):
    assert compute_energy(U, RF, PITCH, BOTTOM_DIAMETER) is None


#                                                              coilable upgrade
# =============================================================================


@pytest.mark.parametrize(
    "coilable, e_max, expected",
    [
        (0, 0.5, 0),  # not coilable: never upgraded
        (None, 0.5, None),  # failed buckling stage: label unknown
        (1, None, 1),  # E_max unavailable: stays binary
        (1, float("nan"), 1),
        (1, 0.01, 1),  # below threshold
        (1, 0.02, 1),  # boundary: strict inequality
        (1, 0.05, 2),  # above threshold: upgraded
        (2, None, 2),  # idempotent on re-runs
        (2, 0.01, 2),
        (2, 0.5, 2),
    ],
)
def test_upgrade_coilable_truth_table(coilable, e_max, expected):
    assert upgrade_coilable(coilable, e_max, max_strain=0.02) == expected


#                                                                post-processor
# =============================================================================


def make_sample(**outputs):
    return ExperimentSample(
        _input_data={
            "bottom_diameter": BOTTOM_DIAMETER,
            "ratio_pitch": RATIO_PITCH,
        },
        _output_data=outputs,
    )


def test_processor_full_coilable_sample():
    strain, stress = triangle_curve()
    U, RF = fields_from_curve(strain, stress)
    sample = make_sample(
        coilable=1.0,
        loads=np.array([10.0, 12.0]),
        U=U,
        RF=RF,
        E_max=0.031,
    )
    out = SupercompressiblePostProcessor().execute(sample).output_data
    assert out["coilable"] == 2
    assert out["sigma_crit"] == pytest.approx(1.2732395, rel=1e-6)
    assert out["energy"] == pytest.approx(5.0, rel=0.02)


def test_processor_coilable_without_e_max_stays_binary():
    strain, stress = triangle_curve()
    U, RF = fields_from_curve(strain, stress)
    sample = make_sample(coilable=1.0, loads=np.array([10.0]), U=U, RF=RF)
    out = SupercompressiblePostProcessor().execute(sample).output_data
    assert out["coilable"] == 1
    assert out["energy"] == pytest.approx(5.0, rel=0.02)


def test_processor_failed_buckling_sample_is_untouched():
    # upstream failure: the columns exist but hold NaN for this sample
    nan = float("nan")
    sample = make_sample(coilable=nan, loads=nan, U=nan, RF=nan)
    out = SupercompressiblePostProcessor().execute(sample).output_data
    assert "sigma_crit" not in out
    assert "energy" not in out
    assert math.isnan(out["coilable"])  # left as-is, not overwritten


def test_processor_non_coilable_sample():
    nan = float("nan")
    sample = make_sample(
        coilable=0.0, loads=np.array([7.0, 9.0]), U=nan, RF=nan
    )
    out = SupercompressiblePostProcessor().execute(sample).output_data
    assert out["coilable"] == 0
    assert out["sigma_crit"] == pytest.approx(7.0 / BOTTOM_AREA * 1e3)
    assert "energy" not in out
