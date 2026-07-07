"""Scalar post-processing (``get_results``) for the supercompressible study.

Derives the scalar quantities of interest of the Bessa et al. (2019)
study from the raw fields collected by the two ABAQUS stages:

* ``sigma_crit`` -- critical buckling stress (kPa): the first buckling
  eigenvalue over the bottom cross-sectional area. The linear-buckle
  step applies a unit reference load, so ``loads[0]`` *is* the critical
  load.
* ``energy`` -- absorbed energy: the area under the cleaned axial
  stress--strain curve of the Riks analysis, or ``None`` when the curve
  has no usable post-peak softening branch (expected for a minority of
  coilable designs; see :func:`compute_energy`).
* ``coilable`` -- upgraded from the binary lin-buckle label to a
  3-class label: ``0`` = not coilable, ``1`` = coilable with maximum
  absolute material strain at most ``max_strain``, ``2`` = coilable and
  exceeding ``max_strain``. The upgrade reads the scalar ``E_max``
  output (max \\|E\\| over the Riks ``E`` field output, extracted by the
  Riks post-processing script) and fires independently of whether the
  energy computation succeeds; when ``E_max`` is unavailable the binary
  label is kept unchanged.

The formulas are a faithful port of the original
``examples/supercompressible/abaqus_modules/get_results.py`` (f3dasm
git history, commit ``410eb18``), with ``E_max`` deliberately decoupled
from the energy computation: the original read it from the Riks ``E``
field before any curve cleaning, not from the applied strain of the
load--displacement curve.
"""

#                                                                       Modules
# =============================================================================

from __future__ import annotations

# Standard
import math
from typing import Optional

# Third-party
import numpy as np
from f3dasm import DataGenerator, ExperimentSample
from scipy import integrate, interpolate, signal

#                                                          Authorship & Credits
# =============================================================================
__author__ = "Martin van der Schelling (M.P.vanderSchelling@tudelft.nl)"
__credits__ = ["Martin van der Schelling"]
__status__ = "Stable"
# =============================================================================
#
# =============================================================================


def _scalar_or_none(value) -> Optional[float]:
    """Normalize a possibly missing sample value to a float or ``None``.

    ``None`` (column missing) and NaN (upstream stage failed, so the
    sample has no value in an otherwise-present column) both map to
    ``None``; anything else is returned as a float.

    Parameters
    ----------
    value
        The raw value read from the sample's merged data dict.

    Returns
    -------
    float or None
        The value as a float, or ``None`` when it is missing.
    """
    if value is None:
        return None
    try:
        if np.isnan(value):
            return None
    except TypeError:
        pass
    return float(value)


def compute_sigma_crit(loads, bottom_diameter: float) -> Optional[float]:
    """Compute the critical buckling stress (kPa).

    The linear-buckle step applies a unit reference load, so the first
    buckling eigenvalue is the critical load; dividing by the bottom
    cross-sectional area gives the critical stress.

    Parameters
    ----------
    loads
        Buckling eigenvalues from the lin-buckle post-processing, or
        ``None``/NaN/empty when that stage failed.
    bottom_diameter : float
        Bottom diameter of the design (mm).

    Returns
    -------
    float or None
        ``loads[0] / (pi * bottom_diameter**2 / 4) * 1e3``, or ``None``
        when no finite first eigenvalue is available.
    """
    if loads is None:
        return None
    loads = np.asarray(loads, dtype=float)
    if loads.size == 0 or not np.isfinite(loads.ravel()[0]):
        return None
    bottom_area = math.pi * bottom_diameter**2 / 4.0
    return float(loads.ravel()[0]) / bottom_area * 1e3


def compute_energy(
    U,
    RF,
    pitch: float,
    bottom_diameter: float,
    additional_strain_thresh: float = 0.05,
    n_interpolation: int = 10000,
) -> Optional[float]:
    """Compute the absorbed energy from the Riks load--displacement data.

    The axial stress--strain curve (``strain = |U_3| / pitch``,
    ``stress = |RF_3| / bottom_area * 1e3`` in kPa) is cleaned to be
    strictly increasing in strain and trimmed of any trailing load
    increase. The energy is only defined when the curve shows a stress
    local maximum followed by at least ``additional_strain_thresh`` more
    strain and ends below strain 1.1; the cleaned curve (padded with a
    ``(1.0, 0.0)`` end point when needed) is then pchip-interpolated on
    ``strain in [0, 1]`` and Simpson-integrated. A ``None`` return for a
    coilable design is expected behavior, not a failure: it means the
    curve has no usable post-peak softening branch.

    All-NaN or missing input (a sample whose Riks stage was skipped or
    failed) returns ``None`` without raising.

    Parameters
    ----------
    U
        ``(3, n_increments)`` displacement history at the top reference
        point; row ``-1`` is the axial (loading) direction.
    RF
        ``(3, n_increments)`` reaction-force history at the top
        reference point; same layout as ``U``.
    pitch : float
        Pitch of the design (``ratio_pitch * bottom_diameter``, mm).
    bottom_diameter : float
        Bottom diameter of the design (mm).
    additional_strain_thresh : float, optional
        Minimum strain the curve must extend past its first stress
        local maximum for the energy to be defined, by default 0.05.
    n_interpolation : int, optional
        Number of interpolation points on ``strain in [0, 1]``, by
        default 10000.

    Returns
    -------
    float or None
        The absorbed energy, or ``None`` when the curve does not
        qualify.
    """
    if U is None or RF is None:
        return None
    U = np.asarray(U, dtype=float)
    RF = np.asarray(RF, dtype=float)
    if U.ndim != 2 or RF.ndim != 2 or U.shape[1] < 2:
        return None

    bottom_area = math.pi * bottom_diameter**2 / 4.0
    u_3 = np.abs(U[-1])
    rf_3 = np.abs(RF[-1])
    strain = u_3 / pitch
    stress = rf_3 / bottom_area * 1e3  # kPa

    # pchip requires strictly increasing strain: drop points that move
    # backwards within numerical jitter (-0.01 <= diff <= 0).
    diff = np.diff(strain)
    idxs = np.where(np.logical_and(diff >= -0.01, diff <= 0.0))[0] + 1
    strain = np.delete(strain, idxs)
    stress = np.delete(stress, idxs)

    if np.size(np.where(np.diff(strain) < 0)) != 0:
        return None

    locmax = signal.argrelextrema(stress, np.greater)
    if np.size(locmax) > 0:
        # Trim a trailing load increase after the softening branch. The
        # size guard is a deliberate deviation from the original, which
        # could index past the start of a fully-consumed curve.
        while stress.size >= 2 and stress[-2] < stress[-1]:
            strain = strain[:-1]
            stress = stress[:-1]

    success = False
    if np.size(locmax) > 0:
        thresh = strain[locmax[0][0]] + additional_strain_thresh
        if strain[-1] > thresh and strain[-1] < 1.1:
            success = True
    if not success:
        return None

    if strain[-1] < 1.0:
        strain = np.append(strain, 1.0)
        stress = np.append(stress, 0.0)

    interp = interpolate.pchip(strain, stress)
    x = np.linspace(0, 1, n_interpolation)
    y = interp(x)
    return float(integrate.simpson(y, x=x))


def upgrade_coilable(
    coilable: Optional[int],
    e_max: Optional[float],
    max_strain: float = 0.02,
) -> Optional[int]:
    """Upgrade the binary coilable label to the 3-class label.

    Mirrors the original ``get_results``: any truthy coilable label
    whose maximum absolute material strain exceeds ``max_strain``
    becomes class ``2``, independent of whether the energy computation
    succeeds. Missing or NaN ``e_max`` leaves the label unchanged (the
    dataset then stays binary), and the upgrade is idempotent: class
    ``2`` stays ``2``.

    Parameters
    ----------
    coilable : int or None
        The (normalized) coilable label: ``0``, ``1``, ``2`` or
        ``None`` when the buckling stage produced no value.
    e_max : float or None
        Maximum absolute strain over the model during the Riks
        analysis (from the ``E`` field output), or ``None``/NaN when
        unavailable.
    max_strain : float, optional
        Strain threshold for the class-2 upgrade, by default 0.02.

    Returns
    -------
    int or None
        The 3-class label, or the input unchanged when no upgrade
        applies.
    """
    if not coilable:
        return coilable
    if e_max is None or math.isnan(e_max) or e_max <= max_strain:
        return coilable
    return 2


class SupercompressiblePostProcessor(DataGenerator):
    """Derive the scalar QoIs from the collected raw simulation fields.

    Runs after both ABAQUS stages have been collected into the
    ExperimentData and stores ``sigma_crit``, ``energy`` and the
    (possibly upgraded) ``coilable`` label as in-memory scalars. Pure
    NumPy/SciPy -- no ABAQUS involved -- so it is meant to run as a
    sequential sweep over all samples (chained after
    :class:`MarkAllOpen`, since a DataGenerator only visits open jobs).

    Samples whose upstream stages failed (all-NaN fields) are handled
    gracefully: nothing is stored for the quantities that cannot be
    computed and the sample is returned without raising.

    Parameters
    ----------
    max_strain : float, optional
        Strain threshold above which a coilable design is upgraded to
        class ``2``, by default 0.02.
    additional_strain_thresh : float, optional
        Post-peak strain margin required for the energy to be defined,
        by default 0.05.
    n_interpolation : int, optional
        Number of interpolation points for the energy integral, by
        default 10000.

    Attributes
    ----------
    max_strain : float
        The class-2 upgrade threshold.
    additional_strain_thresh : float
        The post-peak strain margin for the energy computation.
    n_interpolation : int
        The number of energy-integral interpolation points.
    """

    def __init__(
        self,
        max_strain: float = 0.02,
        additional_strain_thresh: float = 0.05,
        n_interpolation: int = 10000,
    ):
        self.max_strain = float(max_strain)
        self.additional_strain_thresh = float(additional_strain_thresh)
        self.n_interpolation = int(n_interpolation)

    def execute(
        self, experiment_sample: ExperimentSample, **kwargs
    ) -> ExperimentSample:
        """Compute and store the scalar QoIs for one sample.

        Parameters
        ----------
        experiment_sample : ExperimentSample
            The sample holding the design inputs and the collected raw
            fields (``loads``, ``U``, ``RF``, ``coilable`` and, when
            available, ``E_max``).
        **kwargs
            Unused.

        Returns
        -------
        ExperimentSample
            The sample with ``sigma_crit``, ``energy`` and ``coilable``
            stored as in-memory scalars (each only when computable).
        """
        d = experiment_sample.to_dict()

        bottom_diameter = float(d["bottom_diameter"])
        pitch = float(d["ratio_pitch"]) * bottom_diameter

        coilable_raw = _scalar_or_none(d.get("coilable"))
        coilable = int(coilable_raw) if coilable_raw is not None else None

        sigma_crit = compute_sigma_crit(d.get("loads"), bottom_diameter)

        energy = None
        if coilable:  # the Riks stage only ran for coilable designs
            energy = compute_energy(
                d.get("U"),
                d.get("RF"),
                pitch=pitch,
                bottom_diameter=bottom_diameter,
                additional_strain_thresh=self.additional_strain_thresh,
                n_interpolation=self.n_interpolation,
            )

        if coilable is not None:
            coilable = upgrade_coilable(
                coilable,
                _scalar_or_none(d.get("E_max")),
                max_strain=self.max_strain,
            )
            experiment_sample.store(name="coilable", object=coilable)
        if sigma_crit is not None:
            experiment_sample.store(name="sigma_crit", object=sigma_crit)
        if energy is not None:
            experiment_sample.store(name="energy", object=energy)
        return experiment_sample
