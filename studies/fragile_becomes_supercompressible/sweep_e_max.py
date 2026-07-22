# ruff: noqa: UP010, UP024, UP031, UP032
"""Sweep the retained Riks odbs of a completed run for the scalar E_max.

Usage (on a compute node -- the ``abaqus`` wrapper is sbatch-only on
Oscar; do not run this from a login/agent shell)::

    abaqus python sweep_e_max.py <run_dir> <out_csv>

Writes one CSV row per ``<run_dir>/riks/<id>`` directory: ``id,E_max``
with ``E_max`` the maximum absolute value over the E11/E33 components
of the Riks ``E`` field output across all frames (matching the original
``get_results`` and the extraction in ``supercompressible_riks_pp.py``),
the literal ``absent`` when the odb holds no ``E`` field, or ``error``
when the odb could not be read. The ``absent`` marker doubles as the
presence check: if the first rows already read ``absent``, the retained
odbs cannot support the 3-class coilable upgrade (the dataset then
stays binary; future runs need an explicit ``E`` field-output request).

Runs license-free (``abaqus python`` does not check out a CAE token),
so it needs no concurrency cap: a single sequential process over ~700
odbs finishes within a few hours. Feed the CSV to
``backfill_scalars.py --e-max-csv``.

This file is executed by ABAQUS's own Python interpreter and must stay
Python-2 compatible; do not modernize the syntax.
"""

from __future__ import print_function

import glob
import os
import sys

from odbAccess import openOdb

JOB_ODB = "SUPERCOMPRESSIBLE_RIKS.odb"
DIRECTIONS = (1, 3)


def e_max_of_odb(odb_path):
    """Return max |E| (components E11/E33) of one odb, or None if no E."""
    odb = openOdb(odb_path, readOnly=True)
    try:
        step = odb.steps[odb.steps.keys()[-1]]
        element_set = odb.rootAssembly.elementSets[" ALL ELEMENTS"]
        e_max = None
        for frame in step.frames:
            if "E" not in frame.fieldOutputs.keys():
                continue
            outputs = (
                frame.fieldOutputs["E"].getSubset(region=element_set).values
            )
            for output in outputs:
                for direction in DIRECTIONS:
                    value = abs(output.data[direction - 1])
                    if e_max is None or value > e_max:
                        e_max = value
        return e_max
    finally:
        odb.close()


def main(run_dir, out_csv):
    pattern = os.path.join(run_dir, "riks", "*", JOB_ODB)
    odb_paths = sorted(
        glob.glob(pattern),
        key=lambda p: int(os.path.basename(os.path.dirname(p))),
    )
    if not odb_paths:
        print("No odbs found under %s" % pattern)
        sys.exit(1)

    with open(out_csv, "w") as f:
        f.write("id,E_max\n")
        for i, odb_path in enumerate(odb_paths):
            job_id = os.path.basename(os.path.dirname(odb_path))
            try:
                e_max = e_max_of_odb(odb_path)
            except Exception as exc:
                print("id %s: FAILED (%s)" % (job_id, exc))
                f.write("%s,error\n" % job_id)
                f.flush()
                continue
            value = "absent" if e_max is None else "%.10g" % float(e_max)
            f.write("%s,%s\n" % (job_id, value))
            f.flush()
            print("[%d/%d] id %s: %s" % (i + 1, len(odb_paths), job_id, value))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
