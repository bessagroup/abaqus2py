"""
Abaqus Simulator
"""

#                                                                       Modules
# =============================================================================

# Standard
from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Local
from .io import (
    DEFAULT_JOBNAME,
    FILENAME_POSTPROCESS,
    FILENAME_PREPROCESS,
    FILENAME_SIMINFO,
    create_postprocess_script,
    create_preprocess_script,
    remove_temporary_files,
    wait_until_text_verification,
    write_sim_info,
)

#                                                          Authorship & Credits
# =============================================================================
__author__ = "Martin van der Schelling (M.P.vanderSchelling@tudelft.nl)"
__credits__ = ["Martin van der Schelling"]
__status__ = "Alpha"
# =============================================================================
#
# =============================================================================

logger = logging.getLogger("abaqus2py")

# Markers Abaqus writes to its message file when an analysis terminates
# without completing. Used to fail fast instead of waiting for the timeout.
ABAQUS_FAILURE_MARKERS = ("THE ANALYSIS HAS NOT BEEN COMPLETED",)


def abaqus_call(script: Path) -> None:
    """
    Call Abaqus with a python script

    Parameters
    ----------
    script : Path
        Path to the python script

    Raises
    ------
    subprocess.CalledProcessError
        If the ``abaqus`` command exits with a non-zero status.
    """
    subprocess.run(
        ["abaqus", "cae", f"noGUI={script.with_suffix('.py')}", "-mesa"],
        check=True,
    )


def abaqus_submit(inp_file: Path, num_cpus: int) -> None:
    """
    Submit the simulation to Abaqus

    Parameters
    ----------
    inp_file : Path
        Path to the input file
    num_cpus : int
        Number of CPUs to use for the simulation

    Raises
    ------
    subprocess.CalledProcessError
        If the ``abaqus`` command exits with a non-zero status.
    """
    subprocess.run(
        ["abaqus", f"job={inp_file}", f"cpus={num_cpus}"],
        check=True,
    )


def _resolve_name(sim_params: dict[str, Any], index: int) -> str:
    """Return the sub-directory name for a single simulation.

    Uses the ``"name"`` key from ``sim_params`` if present, otherwise falls
    back to ``"{DEFAULT_JOBNAME}_{index}"``.
    """
    if "name" in sim_params:
        return str(sim_params["name"])
    return f"{DEFAULT_JOBNAME}_{index}"


@dataclass
class AbaqusSimulator:
    """
    Abaqus simulator class

    Parameters
    ----------
    num_cpus : int
        Number of CPUs to use for the simulation.
    delete_odb : bool
        If True, the created ODB file is removed after post-processing.
        Can be used to save disk space, default is False.
    delete_temp_files : bool
        If True, temporary files created by Abaqus are removed after
        the simulation, default is False.
    working_directory : Path
        Working directory where subdirectories will be created
        for simulation results. Defaults to the current working directory.
    max_waiting_time : int
        Maximum time to wait in seconds after submitting a job, default is 60.
        This is a workaround to wait for the job to finish.
    """

    num_cpus: int = 1
    delete_odb: bool = False
    delete_temp_files: bool = False
    working_directory: Path = field(default_factory=Path.cwd)
    max_waiting_time: int = 60

    def __post_init__(self) -> None:
        """
        Normalize and set defaults for dataclass fields.
        - Ensure working_directory is a Path.
        """
        self.working_directory = Path(self.working_directory)

    #                                                            Public methods
    # =========================================================================

    def preprocess(
        self,
        py_file: str,
        function_name: str = "main",
        simulation_parameters: Optional[
            Iterable[dict[str, Any]] | dict[str, Any]
        ] = None,
    ):
        """
        Create the input files (.inp) for the simulation with a
        preprocessing script

        Parameters
        ----------
        py_file : str
            Path to the python file
        function_name : str
            Name of the function to call, default is "main"
        simulation_parameters : dict | Iterable[dict], optional
            Key-word arguments with the simulation parameters
        """

        # Create an empty dictionary if no simulation parameters are given
        if simulation_parameters is None:
            simulation_parameters = {}

        if isinstance(simulation_parameters, dict):
            simulation_parameters = [simulation_parameters]

        # Loop over the simulation parameters
        for index, sim_params in enumerate(simulation_parameters):
            name = _resolve_name(sim_params, index)

            _ = _preprocess(
                py_file=Path(py_file),
                working_dir=self.working_directory / name,
                function_name=function_name,
                delete_temp_files=self.delete_temp_files,
                **sim_params,
            )

    def submit(self, inp_files: Iterable[str] | str | Path) -> None:
        """
        Submit the simulation to Abaqus

        Parameters
        ----------
        inp_files : str | Path | list
            Path to the input file(s)
        """
        if isinstance(inp_files, (str, Path)):
            inp_files = [inp_files]

        for inp_file in inp_files:
            _submit(
                inp_file=Path(inp_file),
                num_cpus=self.num_cpus,
                delete_temp_files=self.delete_temp_files,
            )

    def postprocess(
        self,
        py_file: str,
        odb_files: Iterable[str] | str | Path,
        function_name: str = "main",
    ) -> None:
        """
        Run a postprocessing procedure; where the odb file is read and the
        results are processed

        Parameters
        ----------
        py_file : str
            Path to the python file
        odb_files : str | Path | list
            Path to the odb file(s)
        function_name : str
            Name of the function to call, default is "main"
        """
        if isinstance(odb_files, (str, Path)):
            odb_files = [odb_files]

        for odb_file in odb_files:
            _postprocess(
                delete_temp_files=self.delete_temp_files,
                delete_odb=self.delete_odb,
                python_file=Path(py_file),
                odb_file=Path(odb_file).with_suffix(".odb"),
                function_name=function_name,
            )

    def run(
        self,
        py_file: str,
        function_name: str = "main",
        post_py_file: Optional[str] = None,
        simulation_parameters: Optional[
            Iterable[dict[str, Any]] | dict[str, Any]
        ] = None,
        submit_job: bool = True,
        post_function_name: Optional[str] = None,
    ):
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
        simulation_parameters : dict | Iterable[dict], optional
            Key-word arguments with the simulation parameters
        submit_job : bool
            Whether to submit the job to Abaqus, default is True
        post_function_name : str, optional
            Name of the post-processing function to call. Defaults to
            ``function_name`` when not given, so the pre- and post-processing
            scripts may use different entry-point names.
        """

        # Create an empty dictionary if no simulation parameters are given
        if simulation_parameters is None:
            simulation_parameters = {}

        if isinstance(simulation_parameters, dict):
            simulation_parameters = [simulation_parameters]

        if post_function_name is None:
            post_function_name = function_name

        # If an iterable; loop over the simulation parameters
        for index, sim_params in enumerate(simulation_parameters):
            name = _resolve_name(sim_params, index)

            inp_file: Path = _preprocess(
                delete_temp_files=self.delete_temp_files,
                py_file=Path(py_file),
                working_dir=self.working_directory / name,
                function_name=function_name,
                **sim_params,
            )

            # The job, the completion waits and the post-processing only make
            # sense once a job has actually been submitted; otherwise we would
            # poll for .log/.msg files that are never created and time out.
            if submit_job:
                _submit(
                    inp_file=inp_file,
                    num_cpus=self.num_cpus,
                    delete_temp_files=self.delete_temp_files,
                )

                wait_until_text_verification(
                    working_dir=self.working_directory / name,
                    file_extension=".log",
                    text="Begin Analysis Input File Processor",
                    max_waiting_time=self.max_waiting_time,
                )

                # Workaround to wait for the job to finish
                wait_until_text_verification(
                    working_dir=self.working_directory / name,
                    file_extension=".msg",
                    text="JOB TIME SUMMARY",
                    max_waiting_time=self.max_waiting_time,
                    failure_texts=ABAQUS_FAILURE_MARKERS,
                )

                if post_py_file is not None:
                    _postprocess(
                        delete_temp_files=self.delete_temp_files,
                        delete_odb=self.delete_odb,
                        python_file=Path(post_py_file),
                        function_name=post_function_name,
                        odb_file=inp_file.with_suffix(".odb"),
                    )


def _submit(inp_file: Path, num_cpus: int, delete_temp_files: bool) -> None:
    """
    Submit the simulation to Abaqus

    Parameters
    ----------
    inp_file : Path
        Path to the inp file
    """

    logger.debug(f"Submitting {inp_file.stem} in {inp_file.parent}")

    # Save current working directory and always restore it, even if the
    # submission raises, so the caller's cwd is never left changed.
    cwd = Path.cwd()
    try:
        os.chdir(inp_file.parent)
        abaqus_submit(inp_file=inp_file.stem, num_cpus=num_cpus)
    finally:
        os.chdir(cwd)

    logger.debug(f"Submitted {inp_file.stem} in {inp_file.parent}")

    if delete_temp_files:
        remove_temporary_files(directory=inp_file.parent)


def _preprocess(
    delete_temp_files: bool,
    py_file: Path,
    working_dir: Path,
    function_name: str,
    **simulation_parameters,
) -> Path:
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

    # Remove stale artefacts from a previous run in this directory. Otherwise
    # the .inp lookup below and the completion poll in run() could match files
    # left behind by an earlier run and report it as the current job.
    remove_temporary_files(
        directory=working_dir,
        file_types=[".inp", ".log", ".msg", ".odb", ".sta", ".dat", ".lck"],
    )

    # Write a pickle file with the simulation parameters
    write_sim_info(sim_info=simulation_parameters, working_dir=working_dir)

    # Create the preprocessing script
    create_preprocess_script(
        working_dir=working_dir,
        python_file=py_file,
        function_name=function_name,
    )

    # Run abaqus
    abaqus_call(working_dir / FILENAME_PREPROCESS)

    if delete_temp_files:
        (working_dir / FILENAME_PREPROCESS).with_suffix(".py").unlink(
            missing_ok=True
        )
        (working_dir / FILENAME_SIMINFO).with_suffix(".pkl").unlink(
            missing_ok=True
        )

    logger.debug(f"Preprocessing finished with {py_file} in {working_dir}")

    # Search the subdirectory for the .inp file and return the path. Stale
    # .inp files were cleared above, so anything found here was created by the
    # call above; more than one is ambiguous and treated as an error.
    inp_files = sorted(working_dir.glob("*.inp"))
    if not inp_files:
        raise FileNotFoundError(
            f"No .inp file created in the working directory: {working_dir}"
        )
    if len(inp_files) > 1:
        raise RuntimeError(
            f"Expected a single .inp file in {working_dir}, found "
            f"{len(inp_files)}: {[f.name for f in inp_files]}"
        )
    return inp_files[0]


def _postprocess(
    delete_temp_files: bool,
    delete_odb: bool,
    python_file: Path,
    function_name: str,
    odb_file: Path,
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

    logger.debug(f"Postprocessing started with {python_file} for {odb_file}")

    # Create the postprocessing script
    create_postprocess_script(
        working_dir=odb_file.parent,
        python_file=python_file,
        odb_file=odb_file,
        function_name=function_name,
    )

    abaqus_call(odb_file.parent / FILENAME_POSTPROCESS)

    if delete_temp_files:
        (odb_file.parent / FILENAME_POSTPROCESS).with_suffix(".py").unlink(
            missing_ok=True
        )

    if delete_odb:
        odb_file.unlink(missing_ok=True)

    logger.debug(f"Postprocessing finished with {python_file} for {odb_file}")
