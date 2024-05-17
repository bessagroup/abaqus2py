"""
IO functions for the abaqus2py package.
"""

#                                                                       Modules
# =============================================================================

# Standard
import pickle
from pathlib import Path
from time import sleep, time
from typing import List

# Local
from ._logger import logger

#                                                          Authorship & Credits
# =============================================================================
__author__ = "Martin van der Schelling (M.P.vanderSchelling@tudelft.nl)"
__credits__ = ["Martin van der Schelling"]
__status__ = "Alpha"
# =============================================================================
#
# =============================================================================

FILENAME_PREPROCESS = "preprocess"
FILENAME_SUBMIT = "execute"
FILENAME_POSTPROCESS = "post"
FILENAME_SIMINFO = "sim_info"
DEFAULT_JOBNAME = "simulation"

# =============================================================================


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
    filename = working_dir / Path(FILENAME_SIMINFO).with_suffix('.pkl')
    with open(filename, "wb") as fp:
        pickle.dump(sim_info, fp, protocol=0)


def create_preprocess_script(
        working_dir: Path, python_file: Path, function_name: str):
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
    with open(
        f"{working_dir / Path(FILENAME_PREPROCESS).with_suffix('.py')}",
            "w") as f:
        f.write("import os\n")
        f.write("import sys\n")
        f.write("import pickle\n")
        f.write(f"sys.path.extend([r'{python_file.parent}'])\n")
        f.write(
            f"from {python_file.stem} import {function_name}\n"
        )
        f.write(
            f"with open(r'{working_dir / Path(FILENAME_SIMINFO).with_suffix('.pkl')}', 'rb') as f:\n")  # NOQA
        f.write("    dict = pickle.load(f)\n")
        f.write(f"os.chdir(r'{working_dir}')\n")
        f.write(f"{function_name}(dict)\n")


def create_postprocess_script(
        working_dir: Path, python_file: Path,
        odb_file: Path, function_name: str):
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

    with open(
        f"{working_dir / Path(FILENAME_POSTPROCESS).with_suffix('.py')}",
            "w") as f:
        f.write("import os\n")
        f.write("import sys\n")
        f.write("from abaqus import session\n")
        f.write(f"sys.path.extend([r'{python_file.parent}'])\n")
        f.write(
            f"from {python_file.stem} import {function_name}\n"
        )
        f.write((f"odb = session.openOdb("
                f"name=r'{odb_file.with_suffix('.odb')}')\n"))
        f.write(f"os.chdir(r'{working_dir}')\n")
        f.write(f"{function_name}(odb)\n")


def remove_temporary_files(
    directory: Path,
    file_types: List[str] = [".log", ".lck", ".SMABulk",
                             ".rec", ".SMAFocus",
                             ".exception", ".simlog", ".023", ".exception"],
) -> None:
    """Remove files of specified types in a directory.

    Parameters
    ----------
    directory : Path
        Target folder.
    file_types : list
        List of file extensions to be removed, default is a list of Abaqus
        temporary files (.log, .lck, .SMABulk, .rec, .SMAFocus, .exception,
        .simlog, .023, .exception)

    Notes
    -----
    This function removes files with the specified extensions in the target
    directory. This is useful for removing temporary files created by Abaqus
    during the simulation process.
    """
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
        max_waiting_time: int) -> None:
    # workaround
    # sleep(max_waiting_time)
    start_time = time()
    logger.debug(f"Start time: {start_time}")
    success = False

    while (time() - start_time < max_waiting_time):
        logger.debug((
            f"waiting for {file_extension} file "
            f"({time() - start_time} < {max_waiting_time})"))
        if not any(working_dir.glob(f"*{file_extension}")):
            logger.debug(f"no {file_extension} file found")
            sleep(1)
            continue

        filename = working_dir.glob(f"*{file_extension}").__next__()
        logger.debug(f"found {filename} file!")
        with open(filename, 'r') as file:
            if text in file.read():
                success = True
                logger.debug(f"found {text} in {file_extension} file!")
                return

        sleep(1)

    if not success:
        raise TimeoutError(
            (f"Did not find {text} in {file_extension} file "
             f"({working_dir}) within "
             f"{max_waiting_time} seconds")
        )
