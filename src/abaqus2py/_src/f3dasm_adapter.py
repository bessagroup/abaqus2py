"""
Port to f3dasm framework for the Abaqus simulator
"""

#                                                                       Modules
# =============================================================================

# Standard
import pickle
from pathlib import Path
from typing import Any, Optional

# Third-party
import numpy as np
from f3dasm import DataGenerator, ExperimentSample

# Local
from .abaqus_simulator import AbaqusSimulator
from .io import DEFAULT_JOBNAME

#                                                          Authorship & Credits
# =============================================================================
__author__ = "Martin van der Schelling (M.P.vanderSchelling@tudelft.nl)"
__credits__ = ["Martin van der Schelling"]
__status__ = "Alpha"
# =============================================================================
#
# =============================================================================


class F3DASMAbaqusSimulator(DataGenerator):
    """f3dasm :class:`DataGenerator` adapter around :class:`AbaqusSimulator`.

    Wrap a pair of Abaqus pre- and post-processing Python scripts so they can
    be evaluated over an :class:`f3dasm.ExperimentData` via the standard
    :meth:`DataGenerator.call` entry point.

    Parameters
    ----------
    py_file : str
        Path to the Python file containing the pre-processing function.
    function_name : str, optional
        Name of the callable to invoke inside ``py_file`` (and inside
        ``post_py_file`` when ``post_function_name`` is not given), by default
        ``"main"``.
    post_py_file : str, optional
        Path to the Python file containing the post-processing function.
        If None, no post-processing step is run.
    post_function_name : str, optional
        Name of the callable to invoke inside ``post_py_file``. Defaults to
        ``function_name`` when not given.
    num_cpus : int, optional
        Number of CPUs to use for the simulation, by default 1.
    delete_odb : bool, optional
        Delete the ODB file after post-processing, by default False.
    delete_temp_files : bool, optional
        Delete Abaqus temporary files after the simulation, by default False.
    working_directory : str or Path, optional
        Working directory where the simulation will be executed. Defaults to
        the current working directory.
    max_waiting_time : int, optional
        Maximum waiting time (seconds) for the Abaqus job to finish, by
        default 60.

    Attributes
    ----------
    simulator : AbaqusSimulator
        Underlying Abaqus simulator instance configured from the init args.
    py_file : str
        Path to the pre-processing Python file.
    function_name : str
        Name of the entry-point function in ``py_file``.
    post_py_file : str or None
        Path to the post-processing Python file, or None if not set.
    post_function_name : str
        Name of the entry-point function in ``post_py_file``.

    Notes
    -----
    Callers must pass ``pass_id=True`` to :meth:`DataGenerator.call` so that
    the job index is forwarded into :meth:`execute` as the ``id`` keyword
    argument; this index is used as the per-sample sub-directory name.
    """

    def __init__(
        self,
        py_file: str,
        function_name: str = "main",
        post_py_file: Optional[str] = None,
        num_cpus: int = 1,
        delete_odb: bool = False,
        delete_temp_files: bool = False,
        working_directory: Optional[str] = None,
        max_waiting_time: int = 60,
        post_function_name: Optional[str] = None,
    ):
        simulator_kwargs: dict[str, Any] = {
            "num_cpus": num_cpus,
            "delete_odb": delete_odb,
            "delete_temp_files": delete_temp_files,
            "max_waiting_time": max_waiting_time,
        }
        if working_directory is not None:
            simulator_kwargs["working_directory"] = Path(working_directory)

        self.simulator = AbaqusSimulator(**simulator_kwargs)

        self.py_file = py_file
        self.function_name = function_name
        self.post_py_file = post_py_file
        self.post_function_name = post_function_name

    def execute(
        self,
        experiment_sample: ExperimentSample,
        id: Optional[int] = None,
        **kwargs,
    ) -> ExperimentSample:
        """Run the Abaqus simulation for a single experiment sample.

        Builds the simulation parameter dictionary from the sample's input
        data, uses the f3dasm-supplied job ``id`` as the sub-directory name,
        runs the underlying :class:`AbaqusSimulator`, and loads the resulting
        ``results.pkl`` back onto the experiment sample.

        Parameters
        ----------
        experiment_sample : ExperimentSample
            The sample whose input data drives the simulation and whose
            outputs will be updated from ``results.pkl``.
        id : int, optional
            The job index of this sample, forwarded by f3dasm when
            :meth:`DataGenerator.call` is invoked with ``pass_id=True``. Used
            as the per-sample sub-directory name.
        **kwargs
            Additional keyword arguments merged into the simulation
            parameters passed to ``py_file``'s entry-point function.

        Returns
        -------
        ExperimentSample
            The same sample, with simulation outputs stored via
            :meth:`ExperimentSample.store`. Scalar outputs (Python and numpy
            ``int``/``float``/``bool`` and ``str``) are stored in memory;
            other objects (arrays, lists, ...) are written to disk.
        """
        sim_parameters = experiment_sample.to_dict()
        if id is not None and "name" not in sim_parameters:
            sim_parameters["name"] = str(id)
        sim_parameters.update(kwargs)
        sim_parameters.setdefault("name", f"{DEFAULT_JOBNAME}_0")

        self.simulator.run(
            py_file=self.py_file,
            function_name=self.function_name,
            post_py_file=self.post_py_file,
            simulation_parameters=sim_parameters,
            submit_job=True,
            post_function_name=self.post_function_name,
        )

        results_path = (
            self.simulator.working_directory
            / sim_parameters["name"]
            / "results.pkl"
        )
        with open(results_path, "rb") as f:
            results: dict[str, Any] = pickle.load(
                f, fix_imports=True, encoding="latin1"
            )

        for key, value in results.items():
            # np.isscalar covers Python and numpy int/float/bool/str scalars
            # but not arrays or 0-d ndarrays, which belong on disk.
            to_disk = not np.isscalar(value)
            experiment_sample.store(object=value, name=key, to_disk=to_disk)

        return experiment_sample
