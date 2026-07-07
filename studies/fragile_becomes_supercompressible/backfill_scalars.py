"""Backfill a completed run with the get_results scalars, in place.

Applies the ``get_results`` step of the pipeline to a run that finished
before the step existed, without touching ABAQUS: the raw fields on
disk are enough. The run directory is updated in place -- it stays the
single artifact (mind the scratch purge window when the run lives on
``/oscar/scratch``).

Usage (from this study directory, in the repo environment)::

    uv run python backfill_scalars.py <run_dir> [--e-max-csv sweep.csv]
        [--max-strain 0.02] [--additional-strain-thresh 0.05]
        [--n-interpolation 10000]

Steps:

1. Optionally merge the ``E_max`` column from a ``sweep_e_max.py`` CSV
   into the stored ExperimentData (rows reading ``absent``/``error``
   are skipped: those samples keep a binary coilable label).
2. Re-open all jobs and run :class:`SupercompressiblePostProcessor`
   sequentially -- the exact block the pipeline's ``get_results`` step
   runs, so backfilled and future runs share one code path.
3. Store the updated ExperimentData back into ``<run_dir>``.
"""

#                                                                       Modules
# =============================================================================

from __future__ import annotations

# Standard
import argparse
from pathlib import Path

# Third-party
from f3dasm import ExperimentData

# Local
from post_processing import SupercompressiblePostProcessor

#                                                          Authorship & Credits
# =============================================================================
__author__ = "Martin van der Schelling (M.P.vanderSchelling@tudelft.nl)"
__credits__ = ["Martin van der Schelling"]
__status__ = "Stable"
# =============================================================================
#
# =============================================================================


def load_e_max_csv(path: Path) -> dict[int, float]:
    """Parse a ``sweep_e_max.py`` CSV into an id -> E_max mapping.

    Parameters
    ----------
    path : Path
        Path of the sweep CSV (``id,E_max`` header; values are floats
        or the markers ``absent``/``error``).

    Returns
    -------
    dict[int, float]
        E_max per job id; marker rows are omitted.
    """
    e_max_by_id: dict[int, float] = {}
    lines = Path(path).read_text().splitlines()
    for line in lines[1:]:
        job_id, _, value = line.partition(",")
        if value in ("absent", "error"):
            continue
        e_max_by_id[int(job_id)] = float(value)
    return e_max_by_id


def main() -> None:
    """Parse arguments and backfill the run directory in place."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--e-max-csv", type=Path, default=None)
    parser.add_argument("--max-strain", type=float, default=0.02)
    parser.add_argument("--additional-strain-thresh", type=float, default=0.05)
    parser.add_argument("--n-interpolation", type=int, default=10000)
    args = parser.parse_args()

    data = ExperimentData.from_file(project_dir=args.run_dir)

    if args.e_max_csv is not None:
        e_max_by_id = load_e_max_csv(args.e_max_csv)
        for job_id, e_max in e_max_by_id.items():
            data.data[job_id].store(name="E_max", object=e_max)
        print(f"Merged E_max for {len(e_max_by_id)} samples")

    processor = SupercompressiblePostProcessor(
        max_strain=args.max_strain,
        additional_strain_thresh=args.additional_strain_thresh,
        n_interpolation=args.n_interpolation,
    )
    data = data.mark_all("open")
    data = processor.call(data, mode="sequential")
    data.store(args.run_dir)
    print(f"Stored updated ExperimentData in {args.run_dir}")


if __name__ == "__main__":
    main()
