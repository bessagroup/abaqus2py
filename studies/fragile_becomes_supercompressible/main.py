"""fragile_becomes_supercompressible pipeline (f3dasm Pipeline API).

Reproduces the Bessa et al. (2019) supercompressible metamaterial study as a
two-stage ABAQUS workflow -- a linear buckling analysis followed by a Riks
analysis -- expressed as an :class:`f3dasm.Pipeline`. The pipeline runs
locally or on a SLURM cluster; f3dasm owns all array-job submission,
dependency handling, and synchronization, so the legacy ``hpc.jobid``
coordination (head-node pre-processing, worker ``sleep``/retry loops,
``mode``-dispatched ``simulator.call``) is no longer needed.

Pipeline steps
--------------
1. ``create``     -- build/sample the ExperimentData and store it.
2. ``lin_buckle`` -- run the linear buckling simulation per design (parallel).
3. ``reset``      -- collect the buckling results, then re-open every job so
                     the Riks stage fans out over all designs again.
4. ``riks``       -- run the Riks analysis per design (parallel); the Riks
                     pre-processing consumes the buckling odb from each
                     design's ``lin_buckle/`` sub-directory.
5. ``post``       -- collect the Riks results into the final ExperimentData.
"""

#                                                                       Modules
# =============================================================================

# Standard
import logging
from pathlib import Path
from typing import Optional

# Third-party
import hydra
import numpy as np
import pandas as pd
from f3dasm import (
    Block,
    CollectArrayResults,
    ExperimentData,
    ExperimentSample,
    Pipeline,
    SlurmCluster,
    SlurmResources,
    Step,
    create_sampler,
)
from f3dasm.design import Domain
from omegaconf import DictConfig

from abaqus2py import F3DASMAbaqusSimulator

f3dasm_logger = logging.getLogger("f3dasm")

#                                                          Authorship & Credits
# =============================================================================
__author__ = "Martin van der Schelling (M.P.vanderSchelling@tudelft.nl)"
__credits__ = ["Martin van der Schelling"]
__status__ = "Stable"
# =============================================================================
#
# =============================================================================


#                                                         Custom sampler method
# =============================================================================


def log_normal_sampler(
    domain: Domain,
    n_samples: int,
    mean: float,
    sigma: float,
    seed: Optional[int] = None,
) -> pd.DataFrame:
    """Sampler function for a lognormal distribution.

    Parameters
    ----------
    domain
        Domain object whose names label the sampled columns.
    n_samples
        Number of samples to generate.
    mean
        Mean of the lognormal distribution.
    sigma
        Standard deviation of the lognormal distribution.
    seed
        Seed for the random number generator.

    Returns
    -------
    DataFrame
        pandas DataFrame with the samples.
    """
    rng = np.random.default_rng(seed)
    sampled_imperfections = rng.lognormal(
        mean=mean, sigma=sigma, size=n_samples
    )
    return pd.DataFrame(sampled_imperfections, columns=domain.input_names)


#                                                               Pipeline blocks
# =============================================================================


class StagedAbaqusSimulator(F3DASMAbaqusSimulator):
    """:class:`F3DASMAbaqusSimulator` that writes into a per-run sub-directory.

    The stock adapter takes a fixed ``working_directory`` at construction
    time. Inside a :class:`~f3dasm.Pipeline` the run directory is only known
    at execution time, so this thin subclass resolves the working directory
    against ``experiment_sample.project_dir`` (set by the executor) just
    before each simulation. This keeps ``abaqus2py`` itself decoupled from the
    pipeline machinery while landing the ``lin_buckle/`` and ``riks/`` result
    trees under the pipeline's job directory in both local and SLURM modes.

    Parameters
    ----------
    subdir : str
        Sub-directory of ``experiment_sample.project_dir`` to run in
        (``"lin_buckle"`` or ``"riks"``).
    **kwargs
        Forwarded verbatim to :class:`F3DASMAbaqusSimulator`.

    Attributes
    ----------
    subdir : str
        The per-stage sub-directory name.
    """

    def __init__(self, subdir: str, **kwargs):
        super().__init__(**kwargs)
        self.subdir = subdir

    def execute(
        self,
        experiment_sample: ExperimentSample,
        id: Optional[int] = None,
        **kwargs,
    ) -> ExperimentSample:
        """Point the simulator at ``project_dir/subdir`` and run.

        Parameters
        ----------
        experiment_sample : ExperimentSample
            The sample to simulate; its ``project_dir`` anchors the working
            directory.
        id : int, optional
            Job index forwarded by f3dasm when called with ``pass_id=True``.
        **kwargs
            Additional simulation parameters.

        Returns
        -------
        ExperimentSample
            The sample with its simulation outputs stored.
        """
        working_directory = Path(experiment_sample.project_dir) / self.subdir
        working_directory.mkdir(parents=True, exist_ok=True)
        self.simulator.working_directory = working_directory
        return super().execute(experiment_sample, id=id, **kwargs)


class MarkAllOpen(Block):
    """Re-open every job so the next parallel step fans out over all designs.

    A ``parallel`` :class:`~f3dasm.Step` derives its array size from the
    number of *open* jobs on disk. After the buckling stage finishes, all
    jobs are ``finished``; this block resets them to ``open`` before the Riks
    stage. It replaces the legacy inline ``data.mark_all("open")`` call.
    """

    def call(self, data: ExperimentData, **kwargs) -> ExperimentData:
        """Mark all experiments ``open`` and return the updated data.

        Parameters
        ----------
        data : ExperimentData
            The experiment data whose jobs are re-opened.
        **kwargs : dict
            Unused.

        Returns
        -------
        ExperimentData
            A copy with every job marked ``open``.
        """
        return data.mark_all("open")


#                                                          Pipeline definition
# =============================================================================


def create_experimentdata(project_dir: Path, config: DictConfig) -> None:
    """Build the initial ExperimentData and store it under ``project_dir``.

    Two input modes are supported through ``config.experimentdata``:

    * ``from_file`` -- load a pre-existing ExperimentData directory (the
      default, see ``example_design/``).
    * ``from_sampling`` -- sample the design domain (``config.domain``) with
      the requested f3dasm sampler, then join a lognormally sampled
      imperfection column (see :func:`log_normal_sampler`).

    Parameters
    ----------
    project_dir : Path
        Directory in which the ExperimentData is stored. When invoked from a
        :class:`~f3dasm.Step`, f3dasm passes the resolved run directory.
    config : DictConfig
        Hydra config with ``.experimentdata``, ``.domain`` and
        ``.imperfection`` groups.
    """
    if "from_sampling" in config.experimentdata:
        sampling = config.experimentdata.from_sampling

        domain = Domain.from_yaml(config.domain)
        experimentdata = ExperimentData(domain=domain)
        sampler = create_sampler(sampling.sampler, seed=sampling.seed)
        experimentdata = sampler.call(
            data=experimentdata, n_samples=sampling.n_samples
        )

        # Overlay lognormally distributed imperfections onto the designs.
        domain_imperfections = Domain.from_yaml(config.imperfection.domain)
        sampled_df = log_normal_sampler(
            domain=domain_imperfections,
            n_samples=len(experimentdata),
            mean=config.imperfection.mean,
            sigma=config.imperfection.sigma,
            seed=sampling.seed,
        )
        imperfections = ExperimentData(
            domain=domain_imperfections,
            input_data=sampled_df,
        )
        experimentdata = experimentdata.join(imperfections)
    else:
        experimentdata = ExperimentData.from_yaml(config.experimentdata)

    experimentdata.store(project_dir)


def build_pipeline(config: DictConfig) -> Pipeline:
    """Construct the two-stage supercompressible pipeline.

    Parameters
    ----------
    config : DictConfig
        Hydra configuration, including the ABAQUS script paths under
        ``config.scripts``.

    Returns
    -------
    Pipeline
        The configured five-step pipeline.
    """
    simulator_lin_buckle = StagedAbaqusSimulator(
        subdir="lin_buckle",
        py_file=config.scripts.lin_buckle_pre,
        post_py_file=config.scripts.lin_buckle_post,
        max_waiting_time=60,
    )
    simulator_riks = StagedAbaqusSimulator(
        subdir="riks",
        py_file=config.scripts.riks_pre,
        post_py_file=config.scripts.riks_post,
        max_waiting_time=120,
    )

    return Pipeline(
        name="fragile_becomes_supercompressible",
        steps=[
            Step(
                name="create",
                block=create_experimentdata,
                resources=SlurmResources(
                    time="00:10:00", mem="2G", cpus_per_task=1
                ),
                kwargs={"config": config},
            ),
            Step(
                name="lin_buckle",
                block=simulator_lin_buckle,
                dependency="afterok",
                parallel=True,
                resources=SlurmResources(
                    time="00:30:00", mem="4G", cpus_per_task=1
                ),
                kwargs={"pass_id": True},
            ),
            Step(
                name="reset",
                block=CollectArrayResults(cleanup=True) >> MarkAllOpen(),
                dependency="afterany",
                resources=SlurmResources(
                    time="00:10:00", mem="2G", cpus_per_task=1
                ),
            ),
            Step(
                name="riks",
                block=simulator_riks,
                dependency="afterok",
                parallel=True,
                resources=SlurmResources(
                    time="01:00:00", mem="4G", cpus_per_task=1
                ),
                kwargs={"pass_id": True},
            ),
            Step(
                name="post",
                block=CollectArrayResults(cleanup=True),
                dependency="afterany",
                resources=SlurmResources(
                    time="00:10:00", mem="2G", cpus_per_task=1
                ),
            ),
        ],
    )


@hydra.main(config_path=".", config_name="config", version_base=None)
def main(config: DictConfig) -> None:
    """Build and run the pipeline.

    Parameters
    ----------
    config
        Configuration parameters defined in ``config.yaml``.
    """
    f3dasm_logger.setLevel(config.log_level)

    pipeline = build_pipeline(config)

    cluster = (
        SlurmCluster.from_yaml(config.cluster)
        if config.cluster.enabled
        else None
    )
    rootdir = Path(config.rootdir) if config.rootdir else None

    pipeline.run(mode=config.mode, cluster=cluster, rootdir=rootdir)


if __name__ == "__main__":
    main()
