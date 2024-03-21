"""
IO functions for the abaqus2py package.
"""

#                                                                       Modules
# =============================================================================

# Standard
import pickle
from pathlib import Path

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


def write_sim_info(sim_info: dict, working_dir: Path) -> None:
    filename = working_dir / Path(FILENAME_SIMINFO).with_suffix('.pkl')
    with open(filename, "wb") as fp:
        pickle.dump(sim_info, fp, protocol=0)


def create_preprocess_script(
        working_dir: Path, python_file: Path, function_name: str):
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


def create_submit_script(working_dir: Path, inp_file: Path, num_cpus: int):
    with open(
            f"{working_dir / Path(FILENAME_SUBMIT).with_suffix('.py')}",
            "w") as f:
        f.write("from abaqus import mdb\n")
        f.write("import os\n")
        f.write("from abaqusConstants import OFF\n")
        f.write(f"os.chdir(r'{working_dir}')\n")
        f.write(
            f"modelJob = mdb.JobFromInputFile(inputFileName="
            f"r'{inp_file}',"
            f"name='{inp_file.stem}',"
            f"numCpus={num_cpus})\n")
        f.write("modelJob.submit(consistencyChecking=OFF)\n")
        f.write("modelJob.waitForCompletion()\n")


def create_postprocess_script(
        working_dir: Path, python_file: Path,
        odb_file: Path, function_name: str):
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
        f.write(
            f"odb = session.openOdb(\
                name=r'{odb_file.with_suffix('.odb')}')\n")
        f.write(f"os.chdir(r'{working_dir}')\n")
        f.write(f"{function_name}(odb)\n")


def remove_files(
    directory: str,
    file_types: list = [".log", ".lck", ".SMABulk",
                        ".rec", ".SMAFocus",
                        ".exception", ".simlog", ".023", ".exception"],
) -> None:
    """Remove files of specified types in a directory.

    Parameters
    ----------
    directory : str
        Target folder.
    file_types : list
        List of file extensions to be removed.
    """
    # Create a Path object for the directory
    dir_path = Path(directory)

    for target_file in file_types:
        # Use glob to find files matching the target extension
        target_files = dir_path.glob(f"*{target_file}")

        # Remove the target files if they exist
        for file in target_files:
            if file.is_file():
                file.unlink()
