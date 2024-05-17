"""
Abaqus Simulator
"""

#                                                                       Modules
# =============================================================================

# Standard
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

# Local
from ._logger import logger
from .io import (DEFAULT_JOBNAME, FILENAME_POSTPROCESS, FILENAME_PREPROCESS,
                 FILENAME_SIMINFO, create_postprocess_script,
                 create_preprocess_script, remove_temporary_files,
                 wait_until_text_verification, write_sim_info)

#                                                          Authorship & Credits
# =============================================================================
__author__ = "Martin van der Schelling (M.P.vanderSchelling@tudelft.nl)"
__credits__ = ["Martin van der Schelling"]
__status__ = "Alpha"
# =============================================================================
#
# =============================================================================


def abaqus_call(script: Path) -> None:
    """
    Call Abaqus with a python script

    Parameters
    ----------
    script : Path
        Path to the python script
    """
    os.system(f"abaqus cae noGUI={script.with_suffix('.py')} -mesa")


def abaqus_submit(inp_file: Path, num_cpus: int) -> None:
    """
    Submit the simulation to Abaqus

    Parameters
    ----------
    inp_file : Path
        Path to the input file
    num_cpus : int
        Number of CPUs to use for the simulation
    """
    os.system(f"abaqus job={inp_file} cpus={num_cpus}")


class AbaqusSimulator:
    def __init__(self, num_cpus: int = 1,
                 delete_odb: bool = False,
                 delete_temp_files: bool = False,
                 working_directory: Optional[str | Path] = None,
                 max_waiting_time: int = 60):
        """
        Abaqus simulator class

        Parameters
        ----------
        num_cpus : int
            Number of CPUs to use for the simulation.
        delete_odb : bool
            If True, the created odb file is removed after post-processing.
            Can be used to save disk space, default is False.
        delete_temp_files : bool
            If True, temporary files created by Abaqus are removed after
            the simulation, default is False.
        working_directory : Path | str
            Working directory where subdirectories will be created
            for simulation results, by default the current working directory.
        max_waiting_time : int
            Maximum time to wait in seconds after submitting a job
            ,default is 60. This is a workaround to wait for the job to finish.

        """
        self.num_cpus = num_cpus
        self.delete_odb = delete_odb
        self.delete_temp_files = delete_temp_files
        self.max_waiting_time = max_waiting_time

        # If None, set to current working directory.
        if working_directory is None:
            self.working_directory = Path.cwd()

        else:
            self.working_directory = Path(working_directory)

#                                                                Public methods
# =============================================================================

    def preprocess(
            self, py_file: str, function_name: str = "main",
            simulation_parameters: Iterable[
                Dict[str, Any]] | Dict[str, Any] = None):
        """
        Create the input files (.inp) for the simulation with a
        preprocessing script

        Parameters
        ----------
        py_file : str
            Path to the python file
        function_name : str
            Name of the function to call, default is "main"
        simulation_parameters : dict | Iterable[dict]
            Key-word arguments with the simulation parameters
        """

        # Create an empty dictionary if no simulation parameters are given
        if simulation_parameters is None:
            simulation_parameters = {}

        if isinstance(simulation_parameters, dict):
            simulation_parameters = [simulation_parameters]

        # Loop over the simulation parameters
        for index, sim_params in enumerate(simulation_parameters):

            # Check if there is a key 'name' in the dictionary
            if "name" in sim_params:
                name = sim_params["name"]

            else:
                name = f"{DEFAULT_JOBNAME}_{index}"

            _ = self._preprocess(
                py_file=Path(py_file),
                working_dir=self.working_directory / str(name),
                function_name=function_name,
                **sim_params)

    def submit(self, inp_files: Iterable[str] | str) -> None:
        """
        Submit the simulation to Abaqus

        Parameters
        ----------
        inp_files : str | list
            Path to the input file(s)
        """
        if isinstance(inp_files, str):
            inp_files = [inp_files]

        for inp_file in inp_files:
            self._submit(inp_file=Path(inp_file))

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
        if isinstance(odb_files, str):
            odb_files = [odb_files]

        for odb_file in odb_files:
            self._postprocess(python_file=Path(py_file),
                              odb_file=Path(odb_file).with_suffix(".odb"),
                              function_name=function_name)

    def run(
            self, py_file: str, function_name: str = "main",
            post_py_file: Optional[str] = None,
            simulation_parameters: Iterable[Dict[str, Any]] | Dict[str, Any]
            = None,
            submit_job: bool = True):
        """
        Run the full simulation process

        Parameters
        ----------
        py_file : str
            Path to the pre-processing python file to create the input file
        function_name : str
            Name of the pre-processing function to call, default is "main"
        post_py_file : str
            Path to the postprocessing python file, optional
        simulation_parameters : dict | Iterable[dict]
            Key-word arguments with the simulation parameters
        submit_job : bool
            Whether to submit the job to Abaqus, default is True
        """

        # Create an empty dictionary if no simulation parameters are given
        if simulation_parameters is None:
            simulation_parameters = {}

        if isinstance(simulation_parameters, dict):
            simulation_parameters = [simulation_parameters]

        # If an iterable; loop over the simulation parameters
        for index, sim_params in enumerate(simulation_parameters):

            # Check if there is a key 'name' in the dictionary
            if "name" in sim_params:
                name = sim_params["name"]

            else:
                name = f"{DEFAULT_JOBNAME}_{index}"

            inp_file = self._preprocess(
                py_file=Path(py_file),
                working_dir=self.working_directory / str(name),
                function_name=function_name,
                **sim_params)

            if submit_job:
                self._submit(inp_file=inp_file)

            wait_until_text_verification(
                working_dir=self.working_directory / str(name),
                file_extension=".log",
                text="Begin Analysis Input File Processor",
                max_waiting_time=self.max_waiting_time)

            # Workaround to wait for the job to finish
            wait_until_text_verification(
                working_dir=self.working_directory / str(name),
                file_extension=".msg",
                text="JOB TIME SUMMARY",
                max_waiting_time=self.max_waiting_time)

            if post_py_file is not None:
                self._postprocess(
                    python_file=Path(post_py_file),
                    function_name=function_name,
                    odb_file=inp_file.with_suffix('.odb'))

#                                                               Private methods
# =============================================================================

    def _submit(self, inp_file: Path) -> None:
        """
        Submit the simulation to Abaqus

        Parameters
        ----------
        inp_file : Path
            Path to the inp file
        """

        logger.debug(f"Submitting {inp_file.stem} in {inp_file.parent}")

        # Save current working directory
        cwd = Path.cwd()

        # Change to the working directory
        os.chdir(inp_file.parent)

        # Submit the simulation
        abaqus_submit(inp_file=inp_file.stem, num_cpus=self.num_cpus)

        # Change back to the original working directory
        os.chdir(cwd)

        logger.debug(f"Submitted {inp_file.stem} in {inp_file.parent}")

        if self.delete_temp_files:
            remove_temporary_files(directory=inp_file.parent)

    def _preprocess(self, py_file: Path, working_dir: Path,
                    function_name: str,
                    **simulation_parameters) -> Path:
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

        Returns
        -------
        Path
            Path to the input file (.inp)
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

        # Search the subdirectory for the .inp file and return the path
        try:
            return working_dir.glob("*.inp").__next__()
        except StopIteration:
            raise FileNotFoundError((
                f"No .inp file created in the "
                f"working directory: {working_dir}"))

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
