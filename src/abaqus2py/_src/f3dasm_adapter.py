"""
Port to f3dasm framework for the Abaqus simulator
"""

#                                                                       Modules
# =============================================================================

# Standard
import pickle
from typing import Any, Dict, Optional

# Third-party
try:
    from f3dasm.datageneration import DataGenerator  # NOQA
except ImportError:
    DataGenerator = object

# Local
from .abaqus_simulator import AbaqusSimulator

#                                                          Authorship & Credits
# =============================================================================
__author__ = "Martin van der Schelling (M.P.vanderSchelling@tudelft.nl)"
__credits__ = ["Martin van der Schelling"]
__status__ = "Alpha"
# =============================================================================
#
# =============================================================================


class F3DASMAbaqusSimulator(DataGenerator):
    def __init__(
            self, py_file: str, function_name: str = "main",
            post_py_file: Optional[str] = None, num_cpus: int = 1,
            delete_odb: bool = False, delete_temp_files: bool = False,
            working_directory: Optional[str] = None,
            max_waiting_time: int = 60):
        """
        f3dasm adapter for the Abaqus simulator

        Parameters
        ----------
        py_file : str
            Path to the Python file containing the simulation function.
        function_name : str
            Name of the simulation function.
        post_py_file : str
            Path to the Python file containing the post-processing function.
        num_cpus : int
            Number of CPUs to use for the simulation.
        delete_odb : bool
            Delete the ODB file after the simulation.
        delete_temp_files : bool
            Delete temporary files after the simulation.
        working_directory : str
            Working directory where the simulation will be executed.
        max_waiting_time : int
            Maximum waiting time for the simulation to finish.
        """

        self.simulator = AbaqusSimulator(
            num_cpus=num_cpus, delete_odb=delete_odb,
            delete_temp_files=delete_temp_files,
            working_directory=working_directory,
            max_waiting_time=max_waiting_time)

        self.py_file = py_file
        self.function_name = function_name
        self.post_py_file = post_py_file

    def execute(self, **kwargs):
        sim_parameters = self.experiment_sample.to_dict()
        sim_parameters["name"] = str(sim_parameters["job_number"])
        sim_parameters.update(kwargs)

        self.simulator.run(
            py_file=self.py_file,
            function_name=self.function_name,
            post_py_file=self.post_py_file,
            simulation_parameters=sim_parameters,
            submit_job=True)

        # Read pickle file
        with open(self.simulator.working_directory / sim_parameters[
                "name"] / "results.pkl", "rb") as f:
            results: Dict[str, Any] = pickle.load(
                f, fix_imports=True, encoding="latin1")

        for key, value in results.items():
            # Check if value is of one of these types: int, float, str
            if isinstance(value, (int, float, str)):
                self.experiment_sample.store(
                    object=value, name=key, to_disk=False)

            else:
                self.experiment_sample.store(
                    object=value, name=key, to_disk=True)
