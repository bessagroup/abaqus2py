"""
IO functions for the abaqus2py package.
"""

#                                                                       Modules
# =============================================================================

# Standard
import logging
import pickle
from collections.abc import Iterable
from pathlib import Path
from time import sleep, time
from typing import Optional

# Local


#                                                          Authorship & Credits
# =============================================================================
__author__ = "Martin van der Schelling (M.P.vanderSchelling@tudelft.nl)"
__credits__ = ["Martin van der Schelling"]
__status__ = "Alpha"
# =============================================================================
#
# =============================================================================

FILENAME_PREPROCESS = "preprocess"
FILENAME_POSTPROCESS = "post"
FILENAME_SIMINFO = "sim_info"
DEFAULT_JOBNAME = "simulation"

# =============================================================================

logger = logging.getLogger("abaqus2py")


def write_sim_info(sim_info: dict, working_dir: Path) -> None:
    """
    Write the simulation information to a pickle file.

    Parameters
    ----------
    sim_info : dict
        Dictionary containing the simulation information.
    working_dir : Path
        Working directory where the pickle file will be saved.
    """
    filename = working_dir / Path(FILENAME_SIMINFO).with_suffix(".pkl")
    with open(filename, "wb") as fp:
        pickle.dump(sim_info, fp, protocol=0)


def create_preprocess_script(
    working_dir: Path, python_file: Path, function_name: str
):
    """
    Create a preprocess script for the simulation.

    Parameters
    ----------
    working_dir : Path
        Working directory where the preprocess script will be saved.
    python_file : Path
        Path to the Python file containing the preprocess function.
    function_name : str
        Name of the preprocess function.
    """
    preprocess_path = working_dir / Path(FILENAME_PREPROCESS).with_suffix(
        ".py"
    )
    siminfo_path = working_dir / Path(FILENAME_SIMINFO).with_suffix(".pkl")
    # Paths are embedded with repr() rather than hand-built r'...' literals so
    # that paths containing quotes, backslashes or other special characters
    # produce valid Python in the generated script.
    with open(preprocess_path, "w") as f:
        f.write("import os\n")
        f.write("import sys\n")
        f.write("import pickle\n")
        f.write(f"sys.path.extend([{repr(str(python_file.parent))}])\n")
        f.write(f"from {python_file.stem} import {function_name}\n")
        f.write(f"with open({repr(str(siminfo_path))}, 'rb') as f:\n")
        f.write("    sim_info = pickle.load(f)\n")
        f.write(f"os.chdir({repr(str(working_dir))})\n")
        f.write(f"{function_name}(sim_info)\n")


def create_postprocess_script(
    working_dir: Path, python_file: Path, odb_file: Path, function_name: str
):
    """
    Create a postprocess script for the simulation.

    Parameters
    ----------
    working_dir : Path
        Working directory where the postprocess script will be saved.
    python_file : Path
        Path to the Python file containing the postprocess function.
    odb_file : Path
        Path to the .odb file to be postprocessed.
    function_name : str
        Name of the postprocess function.
    """

    postprocess_path = working_dir / Path(FILENAME_POSTPROCESS).with_suffix(
        ".py"
    )
    odb_path = odb_file.with_suffix(".odb")
    # Paths are embedded with repr() rather than hand-built r'...' literals so
    # that paths containing quotes, backslashes or other special characters
    # produce valid Python in the generated script.
    with open(postprocess_path, "w") as f:
        f.write("import os\n")
        f.write("import sys\n")
        f.write("from abaqus import session\n")
        f.write(f"sys.path.extend([{repr(str(python_file.parent))}])\n")
        f.write(f"from {python_file.stem} import {function_name}\n")
        f.write(f"odb = session.openOdb(name={repr(str(odb_path))})\n")
        f.write(f"os.chdir({repr(str(working_dir))})\n")
        f.write(f"{function_name}(odb)\n")


def remove_temporary_files(
    directory: Path,
    file_types: Optional[list[str]] = None,
) -> None:
    """Remove files of specified types in a directory.

    Parameters
    ----------
    directory : Path
        Target folder.
    file_types : list of str, optional
        List of file extensions to be removed. If None, a default list of
        Abaqus temporary-file extensions is used (``.log``, ``.lck``,
        ``.SMABulk``, ``.rec``, ``.SMAFocus``, ``.exception``, ``.simlog``,
        ``.023``).

    Notes
    -----
    This function removes files with the specified extensions in the target
    directory. This is useful for removing temporary files created by Abaqus
    during the simulation process.
    """
    if file_types is None:
        file_types = [
            ".log",
            ".lck",
            ".SMABulk",
            ".rec",
            ".SMAFocus",
            ".exception",
            ".simlog",
            ".023",
        ]
    for target_file in file_types:
        # Use glob to find files matching the target extension
        target_files = directory.glob(f"*{target_file}")

        # Remove the target files if they exist
        for file in target_files:
            if file.is_file():
                file.unlink()


def wait_until_text_verification(
    working_dir: Path,
    file_extension: str,
    text: str,
    max_waiting_time: int,
    failure_texts: Optional[Iterable[str]] = None,
) -> None:
    """Poll a directory for a file containing a target text.

    Scans ``working_dir`` for *every* file matching ``*{file_extension}`` and
    succeeds as soon as any of them contains ``text``. Polls once per second
    until ``max_waiting_time`` elapses. If ``failure_texts`` is given and any
    of those markers is found in a matching file, the call fails fast with a
    ``RuntimeError`` instead of waiting for the timeout.

    Parameters
    ----------
    working_dir : Path
        Directory in which to look for the file.
    file_extension : str
        File extension used to find matching files (e.g. ``".log"``). All
        matching files are inspected, not just the first one.
    text : str
        Substring that must be present in a file for the call to succeed.
    max_waiting_time : int
        Maximum time to wait, in seconds.
    failure_texts : Iterable of str, optional
        Substrings that signal the Abaqus job failed. If any is found in a
        matching file, a ``RuntimeError`` is raised immediately. ``None``
        (default) disables failure detection.

    Raises
    ------
    RuntimeError
        If one of ``failure_texts`` is found in a matching file.
    TimeoutError
        If the expected text is not found within ``max_waiting_time`` seconds.
    """
    failure_texts = list(failure_texts) if failure_texts is not None else []
    start_time = time()
    logger.debug(f"Start time: {start_time}")

    while time() - start_time < max_waiting_time:
        logger.debug(
            f"waiting for {file_extension} file "
            f"({time() - start_time} < {max_waiting_time})"
        )
        matches = list(working_dir.glob(f"*{file_extension}"))
        if not matches:
            logger.debug(f"no {file_extension} file found")
            sleep(1)
            continue

        for filename in matches:
            logger.debug(f"found {filename} file!")
            contents = filename.read_text()

            for marker in failure_texts:
                if marker in contents:
                    raise RuntimeError(
                        f"Abaqus reported a failure ('{marker}') in {filename}"
                    )

            if text in contents:
                logger.debug(f"found {text} in {filename}!")
                return

        sleep(1)

    raise TimeoutError(
        f"Did not find {text} in {file_extension} file "
        f"({working_dir}) within "
        f"{max_waiting_time} seconds"
    )
