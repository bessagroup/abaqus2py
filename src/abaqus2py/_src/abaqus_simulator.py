"""
Abaqus Simulator
"""

#                                                                       Modules
# =============================================================================

# Standard
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable

# Local
from ._logger import logger
from .io import (DEFAULT_JOBNAME, FILENAME_POSTPROCESS, FILENAME_PREPROCESS,
                 FILENAME_SIMINFO, create_postprocess_script,
                 create_preprocess_script, remove_temporary_files,
                 write_sim_info)

#                                                          Authorship & Credits
# =============================================================================
__author__ = "Martin van der Schelling (M.P.vanderSchelling@tudelft.nl)"
__credits__ = ["Martin van der Schelling"]
__status__ = "Alpha"
# =============================================================================
#
# =============================================================================

# =============================================================================


def abaqus_call(script: Path) -> None:
    os.system(f"abaqus cae noGUI={script.with_suffix('.py')} -mesa")


def abaqus_submit(inp_file: Path, num_cpus: int) -> None:
    os.system(f"abaqus job={inp_file} cpus={num_cpus}")


class AbaqusSimulator:
    def __init__(self, num_cpus: int = 1,
                 delete_odb: bool = False,
                 delete_temp_files: bool = False,
                 working_directory: Path | str = Path.cwd()):
        """
        Abaqus simulator class

        Parameters
        ----------
        num_cpus : int
            Number of CPUs to use for the simulation
        delete_odb : bool
            Delete the odb file after the simulation
        delete_temp_files : bool
            Delete the temporary files after the simulation
        working_directory : Path | str
            Working directory where subdirectories will be created
            for simulation results
        """
        self.num_cpus = num_cpus
        self.delete_odb = delete_odb
        self.delete_temp_files = delete_temp_files
        self.working_directory = Path(working_directory)

#                                                                Public methods
# =============================================================================

    def preprocess(
            self, py_file: str, function_name: str = "main",
            simulation_parameters: Iterable[
                Dict[str, Any]] | Dict[str, Any] = None) -> Path:
        """
        Create the input files (.inp) for the simulation with a
        preprocessing script

        Parameters
        ----------
        py_file : str
            Path to the python file
        function_name : str
            Name of the function to call, default is "main"
        simulation_parameters : dict | list
            Key-word arguments with the simulation parameters

        Returns
        -------
        Path
            Path to the input file (.inp)
        """

        # Create an empty dictionary if no simulation parameters are given
        if simulation_parameters is None:
            simulation_parameters = {}

        # If an iterable; loop over the simulation parameters
        if isinstance(simulation_parameters, (list, tuple, set)):
            for name, sim_params in enumerate(simulation_parameters):

                # Check if there is a key 'name' in the dictionary
                if "name" not in sim_params:
                    sim_params["name"] = f"{DEFAULT_JOBNAME}_{name}"

                name = sim_params["name"]

                self._preprocess(
                    py_file=Path(py_file),
                    working_dir=self.working_directory / str(name),
                    function_name=function_name,
                    **sim_params)

        else:
            # Check if there is a key 'name' in the dictionary
            if "name" not in simulation_parameters:
                simulation_parameters["name"] = DEFAULT_JOBNAME

            name = simulation_parameters["name"]

            self._preprocess(
                py_file=Path(py_file),
                working_dir=self.working_directory / str(name),
                function_name=function_name,
                **simulation_parameters)

        # return (self.working_directory / str(name)).with_suffix('.inp')

    def submit(self, inp_files: Iterable[str] | str) -> None:
        """
        Submit the simulation to Abaqus

        Parameters
        ----------
        inp_files : str | list
            Path to the input file(s)
        """
        if isinstance(inp_files, (list, tuple, set)):
            for inp_file in inp_files:
                self._submit(inp_file=Path(inp_file),
                             working_dir=Path(inp_file).parent)

        else:
            self._submit(inp_file=Path(inp_files),
                         working_dir=Path(inp_files).parent)

    def postprocess(self, py_file: str, odb_files: Iterable[str] | str,
                    function_name: str = "main") -> None:
        """
        Run a postprocessing procedure; where the odb file is read and the
        results are processed

        Parameters
        ----------
        py_file : str
            Path to the python file
        odb_files : str | list
            Path to the odb file(s)
        function_name : str
            Name of the function to call, default is "main"
        """
        if isinstance(odb_files, (list, tuple, set)):
            for odb_file in odb_files:
                self._postprocess(python_file=Path(py_file),
                                  odb_file=Path(odb_file).with_suffix(".odb"),
                                  function_name=function_name)

        else:
            self._postprocess(python_file=Path(py_file),
                              odb_file=Path(odb_files).with_suffix(".odb"),
                              function_name=function_name)

    # def run(
    #         self, py_file: str, function_name: str = "main",
    #         post_py_file: Optional[str] = None,
    #         simulation_parameters: Iterable[Dict[str, Any]] | Dict[str, Any]
            # = None):

    #     # Create an empty dictionary if no simulation parameters are given
    #     if simulation_parameters is None:
    #         simulation_parameters = {}

    #     # If an iterable; loop over the simulation parameters
    #     if isinstance(simulation_parameters, (list, tuple, set)):
    #         for name, sim_params in enumerate(simulation_parameters):

    #             inp_file = self.preprocess(
    #                 py_file=py_file, function_name=function_name,
    #                 simulation_parameters=sim_params)

    #             self.submit(inp_files=inp_file)

    #             if post_py_file is not None:
    #                 self.postprocess(
    #                     py_file=post_py_file, function_name=function_name,
    #                     odb_files=inp_file.with_suffix('.odb'))

    #     else:
    #         inp_file = self.preprocess(
    #             py_file=py_file, function_name=function_name,
    #             simulation_parameters=simulation_parameters)

    #         self.submit(inp_files=inp_file)

    #         if post_py_file is not None:
    #             self.postprocess(
    #                 py_file=post_py_file, function_name=function_name,
    #                 odb_files=inp_file.with_suffix('.odb'))

#                                                               Private methods
# =============================================================================

    def _submit(self, inp_file: Path, working_dir: Path) -> None:
        """
        Submit the simulation to Abaqus

        Parameters
        ----------
        inp_file : Path
            Path to the inp file
        """

        logger.debug(f"Submitting {inp_file.stem} in {working_dir}")

        # Save current working directory
        cwd = Path.cwd()

        # Change to the working directory
        os.chdir(inp_file.parent)

        # Submit the simulation
        abaqus_submit(inp_file=inp_file.stem, num_cpus=self.num_cpus)

        # Change back to the original working directory
        os.chdir(cwd)

        # # Create the submit script
        # create_submit_script(
        #     working_dir=working_dir, inp_file=inp_file,
        #     num_cpus=self.num_cpus)

        # # Run abaqus
        # abaqus_call(working_dir / FILENAME_SUBMIT)
        # if self.delete_temp_files:
        #     (working_dir / FILENAME_SUBMIT).with_suffix(".py").unlink(
        #         missing_ok=True)

        logger.debug(f"Submitted {inp_file.stem} in {working_dir}")

        if self.delete_temp_files:
            remove_temporary_files(directory=inp_file.parent)

    def _preprocess(self, py_file: Path, working_dir: Path,
                    function_name: str,
                    **simulation_parameters) -> None:
        """
        Create the input files for the simulation with a preprocessing script

        Parameters
        ----------
        py_file : Path
            Path to the python file
        working_dir : Path
            Working directory
        function_name : str
            Name of the function to call
        simulation_parameters : dict
            Key-word arguments with the simulation parameters
        """

        logger.debug(f"Preprocessing started with {py_file} in {working_dir}")

        # Check if the working directory exists, if not create it
        working_dir.mkdir(parents=True, exist_ok=True)

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

        logger.debug(f"Preprocessing finished with {py_file} in {working_dir}")

    def _postprocess(
            self, python_file: Path, function_name: str, odb_file: Path
    ) -> None:
        """
        Run a postprocessing procedure; where the odb file is read and the
        results are processed

        Parameters
        ----------
        python_file : Path
            Path to the python file
        function_name : str
            Name of the function to call
        odb_file : Path
            Path to the odb file
        """

        logger.debug(
            f"Postprocessing started with {python_file} for {odb_file}")

        # Create the postprocessing script
        create_postprocess_script(working_dir=odb_file.parent,
                                  python_file=python_file, odb_file=odb_file,
                                  function_name=function_name)

        abaqus_call(odb_file.parent / FILENAME_POSTPROCESS)

        if self.delete_temp_files:
            (odb_file.parent / FILENAME_POSTPROCESS).with_suffix('.py').unlink(
                missing_ok=True)

        if self.delete_odb:
            odb_file.unlink(missing_ok=True)

        logger.debug(
            f"Postprocessing finished with {python_file} for {odb_file}")
