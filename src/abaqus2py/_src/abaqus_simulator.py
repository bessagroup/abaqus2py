"""
Abaqus Simulator
"""

#                                                                       Modules
# =============================================================================

# Standard
from __future__ import annotations

import os
from pathlib import Path

# Local
from .io import (FILENAME_POSTPROCESS, FILENAME_PREPROCESS, FILENAME_SIMINFO,
                 FILENAME_SUBMIT, create_postprocess_script,
                 create_preprocess_script, create_submit_script,
                 write_sim_info)

#                                                          Authorship & Credits
# =============================================================================
__author__ = "Martin van der Schelling (M.P.vanderSchelling@tudelft.nl)"
__credits__ = ["Martin van der Schelling"]
__status__ = "Alpha"
# =============================================================================
#
# =============================================================================


def abaqus_call(script: Path) -> None:
    os.system(f"abaqus cae noGUI={script.with_suffix('.py')} -mesa")


class AbaqusSimulator:
    def __init__(self, num_cpus: int = 1,
                 delete_odb: bool = False,
                 delete_temp_files: bool = False):
        self.num_cpus = num_cpus
        self.delete_odb = delete_odb
        self.delete_temp_files = delete_temp_files

    def _submit(self, inp_file: Path, working_dir: Path) -> None:

        # Create the submit script
        create_submit_script(
            working_dir=working_dir, inp_file=inp_file, num_cpus=self.num_cpus)

        # Run abaqus
        abaqus_call(working_dir / FILENAME_SUBMIT)
        if self.delete_temp_files:
            (working_dir / FILENAME_SUBMIT).with_suffix(".py").unlink(
                missing_ok=True)

    def _preprocess(self, py_file: Path, working_dir: Path,
                    function_name: str,
                    **simulation_parameters) -> None:

        # Write a pickle file with the simulation parameters
        write_sim_info(sim_info=simulation_parameters,
                       working_dir=working_dir)

        # Create the preprocessing script
        create_preprocess_script(
            working_dir=working_dir,
            python_file=py_file, function_name=function_name)

        # Run abaqus
        abaqus_call(working_dir / FILENAME_PREPROCESS)

        if self.delete_temp_files:
            (working_dir / FILENAME_PREPROCESS).with_suffix(".py").unlink(
                missing_ok=True)
            (working_dir / FILENAME_SIMINFO).with_suffix(".pkl").unlink(
                missing_ok=True)

    def _postprocess(
        self, python_file: Path, odb_file: Path, working_dir: Path,
            function_name: str = "main") -> None:

        # Create the postprocessing script
        create_postprocess_script(working_dir=working_dir,
                                  python_file=python_file, odb_file=odb_file,
                                  function_name=function_name)

        abaqus_call(working_dir / FILENAME_POSTPROCESS)

        if self.delete_temp_files:
            (working_dir / FILENAME_POSTPROCESS).with_suffix('.py').unlink(
                missing_ok=True)
