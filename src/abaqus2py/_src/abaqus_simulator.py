"""
Abaqus Simulator
"""

#                                                                       Modules
# =============================================================================

# Standard
from __future__ import annotations

import logging
import random
import subprocess
import sys
import time
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
    find_marker_lines,
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

# Marker of a solver error line in the Abaqus message file. An analysis can
# reach its JOB TIME SUMMARY (i.e. "complete") and still have failed -- e.g. a
# *BUCKLE step whose eigensolver hits its iteration cap writes ***ERROR to the
# .msg, finishes, and leaves an .odb without mode frames that then breaks
# post-processing with an unrelated-looking error. After the completion wait,
# ``run`` scans the .msg for this marker and raises with the actual solver
# message instead. Set to ``None`` (module attribute) to disable the scan.
ABAQUS_SOLVER_ERROR_MARKER: Optional[str] = "***ERROR"

# Signatures of a *transient* DSLS licensing failure: Abaqus could not reach or
# check out from the license server (server briefly down, a network hiccup, or
# the shared token pool momentarily saturated). Abaqus prints one of these to
# stdout/stderr and exits non-zero. This is distinct from a genuine modelling
# or analysis error, so a call that fails this way is safe to retry.
ABAQUS_LICENSE_ERROR_MARKERS = (
    "Failed to startup licensing",
    "Unable to connect to server",
    "1A000060",
)

# Retry policy for transient license failures (see ``_run_abaqus``). The
# back-off is exponential with additive jitter so that a wide array of workers
# that all hit a saturated license server do not retry in lockstep and re-flood
# it. Tunable by overriding these module attributes.
ABAQUS_LICENSE_MAX_RETRIES = 5
ABAQUS_LICENSE_BACKOFF_BASE = 5.0  # seconds; first back-off ~= this value
ABAQUS_LICENSE_BACKOFF_CAP = 60.0  # seconds; ceiling on the exponential term
ABAQUS_LICENSE_BACKOFF_JITTER = 5.0  # seconds; max random addition per retry


def _emit(stdout: Optional[str], stderr: Optional[str]) -> None:
    """Re-emit captured subprocess output to the parent std streams.

    ``_run_abaqus`` captures Abaqus' output so it can inspect it for a license
    signature; this forwards it on (stdout to stdout, stderr to stderr) so it
    still lands in the job log exactly as if it had never been captured.
    """
    if stdout:
        sys.stdout.write(stdout)
        sys.stdout.flush()
    if stderr:
        sys.stderr.write(stderr)
        sys.stderr.flush()


def _run_abaqus(
    cmd: list[str], *, description: str, cwd: Optional[Path] = None
) -> None:
    """Run an ``abaqus`` command, retrying transient license failures.

    Runs ``cmd`` via :func:`subprocess.run` (capturing output so it can be
    inspected, then re-emitting it via :func:`_emit` so nothing is lost from
    the job log). On a non-zero exit whose output carries an
    :data:`ABAQUS_LICENSE_ERROR_MARKERS` signature, the command is retried up
    to :data:`ABAQUS_LICENSE_MAX_RETRIES` times with exponential back-off and
    jitter. Any other failure is raised immediately, so genuine modelling or
    analysis errors still surface without delay.

    Parameters
    ----------
    cmd : list[str]
        The ``abaqus`` command and its arguments (passed without a shell).
    description : str
        Human-readable label used in the retry log messages
        (e.g. ``"abaqus cae"``).
    cwd : Path, optional
        Working directory to run the command in. ``abaqus cae`` writes its
        replay/recover files (``abaqus.rec``, ``abaqus.rpy``) into the cwd, so
        this must point at a writable location (the per-simulation working
        directory) rather than the -- possibly read-only -- job launch
        directory. ``None`` inherits the current process cwd.

    Raises
    ------
    subprocess.CalledProcessError
        If the command fails for a non-license reason, or still fails with a
        license error after the retry budget is exhausted.
    """
    for attempt in range(ABAQUS_LICENSE_MAX_RETRIES + 1):
        try:
            result = subprocess.run(
                cmd, check=True, capture_output=True, text=True, cwd=cwd
            )
        except subprocess.CalledProcessError as error:
            _emit(error.stdout, error.stderr)
            output = f"{error.stdout or ''}\n{error.stderr or ''}"
            is_license_error = any(
                marker in output for marker in ABAQUS_LICENSE_ERROR_MARKERS
            )
            if not is_license_error or attempt == ABAQUS_LICENSE_MAX_RETRIES:
                raise
            delay = min(
                ABAQUS_LICENSE_BACKOFF_CAP,
                ABAQUS_LICENSE_BACKOFF_BASE * 2**attempt,
            ) + random.uniform(0.0, ABAQUS_LICENSE_BACKOFF_JITTER)
            logger.warning(
                "%s could not obtain an Abaqus license (attempt %d/%d); "
                "retrying in %.1fs.",
                description,
                attempt + 1,
                ABAQUS_LICENSE_MAX_RETRIES + 1,
                delay,
            )
            time.sleep(delay)
        else:
            _emit(result.stdout, result.stderr)
            return


def abaqus_call(script: Path) -> None:
    """
    Call Abaqus with a python script

    The command runs in ``script``'s own directory (the per-simulation
    working directory), so the replay/recover files ``abaqus cae`` drops
    (``abaqus.rec``, ``abaqus.rpy``) land there rather than in the -- possibly
    read-only -- job launch directory.

    Parameters
    ----------
    script : Path
        Path to the python script

    Raises
    ------
    subprocess.CalledProcessError
        If the ``abaqus`` command exits with a non-zero status. Transient
        license-connection failures are retried first (see
        :func:`_run_abaqus`); this is only raised for a genuine failure or
        once the retry budget is exhausted.
    """
    _run_abaqus(
        ["abaqus", "cae", f"noGUI={script.with_suffix('.py')}", "-mesa"],
        description="abaqus cae",
        cwd=script.parent,
    )


def abaqus_submit(inp_file: Path, num_cpus: int) -> None:
    """
    Submit the simulation to Abaqus

    The command runs in ``inp_file``'s own directory (the per-simulation
    working directory) and submits by job name (``job=<stem>``), so Abaqus
    resolves the ``.inp`` and writes all job outputs there rather than in the
    -- possibly read-only -- job launch directory.

    Parameters
    ----------
    inp_file : Path
        Path to the input (``.inp``) file.
    num_cpus : int
        Number of CPUs to use for the simulation

    Raises
    ------
    subprocess.CalledProcessError
        If the ``abaqus`` command exits with a non-zero status. Transient
        license-connection failures are retried first (see
        :func:`_run_abaqus`); this is only raised for a genuine failure or
        once the retry budget is exhausted.
    """
    _run_abaqus(
        ["abaqus", f"job={inp_file.stem}", f"cpus={num_cpus}"],
        description="abaqus job submission",
        cwd=inp_file.parent,
    )


def abaqus_terminate(job_name: str, working_dir: Path) -> None:
    """Best-effort ``abaqus terminate`` of a running job.

    ``abaqus job=...`` is fire-and-forget: the solver runs detached, so when
    a completion wait times out the analysis is still running -- holding
    license tokens, writing files, and leaving a ``.lck`` behind. This asks
    Abaqus to stop it. Failures are logged, never raised: termination is
    cleanup on an already-failing path and must not mask the original
    ``TimeoutError``.

    Parameters
    ----------
    job_name : str
        Name of the Abaqus job to terminate (the ``.inp`` stem).
    working_dir : Path
        The job's working directory; ``abaqus terminate`` resolves the job
        by name relative to its cwd.
    """
    try:
        result = subprocess.run(
            ["abaqus", "terminate", f"job={job_name}"],
            capture_output=True,
            text=True,
            cwd=working_dir,
        )
        _emit(result.stdout, result.stderr)
        if result.returncode != 0:
            logger.warning(
                "Could not terminate Abaqus job %s (exit status %d)",
                job_name,
                result.returncode,
            )
    except OSError as error:
        logger.warning(
            "Could not terminate Abaqus job %s: %s", job_name, error
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
        Maximum total time to wait in seconds after submitting a job, default
        is 60. This is a workaround to wait for the job to finish. When
        ``max_stall_time`` is set, this ceiling only guards against runaway
        jobs and can be set generously (e.g. the scheduler's walltime).
    max_stall_time : int, optional
        Maximum time in seconds to tolerate the job's working directory
        showing no file activity while waiting for completion. A running
        solver continuously updates its output files, so a stall means the
        job died; a slow-but-alive job keeps the wait going up to
        ``max_waiting_time``. ``None`` (default) disables stall detection and
        makes ``max_waiting_time`` the only limit -- which conflates "slow"
        with "dead" and kills healthy long-running jobs.
    """

    num_cpus: int = 1
    delete_odb: bool = False
    delete_temp_files: bool = False
    working_directory: Path = field(default_factory=Path.cwd)
    max_waiting_time: int = 60
    max_stall_time: Optional[int] = None

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

        Raises
        ------
        TimeoutError
            If the job does not finish within ``max_waiting_time`` seconds,
            or -- when ``max_stall_time`` is set -- if its working directory
            shows no file activity for ``max_stall_time`` seconds. The
            (possibly still running) job is terminated via
            :func:`abaqus_terminate` before the error propagates.
        RuntimeError
            If Abaqus reports the analysis failed (see
            :data:`ABAQUS_FAILURE_MARKERS`), or if the completed job's
            ``.msg`` file contains solver error lines (see
            :data:`ABAQUS_SOLVER_ERROR_MARKER`); the error lines are included
            in the message. Raised before post-processing is attempted.
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

                job_dir = self.working_directory / name
                try:
                    # No stall detection here: before the job starts, license
                    # queueing legitimately produces long silences.
                    wait_until_text_verification(
                        working_dir=job_dir,
                        file_extension=".log",
                        text="Begin Analysis Input File Processor",
                        max_waiting_time=self.max_waiting_time,
                    )

                    # Workaround to wait for the job to finish
                    wait_until_text_verification(
                        working_dir=job_dir,
                        file_extension=".msg",
                        text="JOB TIME SUMMARY",
                        max_waiting_time=self.max_waiting_time,
                        failure_texts=ABAQUS_FAILURE_MARKERS,
                        stall_timeout=self.max_stall_time,
                    )
                except TimeoutError:
                    # The detached solver is likely still running; stop it so
                    # it does not keep holding license tokens and leave a
                    # .lck that blocks re-running the job in this directory.
                    abaqus_terminate(
                        job_name=inp_file.stem, working_dir=job_dir
                    )
                    raise

                # An analysis can reach JOB TIME SUMMARY and still have
                # failed (e.g. an eigensolver iteration cap); its .odb is
                # then incomplete and post-processing would fail with a
                # misleading error. Surface the solver's own message instead.
                if ABAQUS_SOLVER_ERROR_MARKER:
                    solver_errors = find_marker_lines(
                        working_dir=job_dir,
                        file_extension=".msg",
                        marker=ABAQUS_SOLVER_ERROR_MARKER,
                    )
                    if solver_errors:
                        raise RuntimeError(
                            f"Abaqus job {inp_file.stem} completed with "
                            f"solver errors in its .msg file: "
                            f"{'; '.join(solver_errors)}"
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

    # abaqus_submit runs in inp_file's directory via subprocess `cwd=`; no
    # process-wide os.chdir, so concurrent submissions can't race on cwd.
    abaqus_submit(inp_file=inp_file, num_cpus=num_cpus)

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
