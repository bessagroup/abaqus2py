"""Tests for :class:`abaqus2py.F3DASMAbaqusSimulator`."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest
from f3dasm import DataGenerator, ExperimentSample

from abaqus2py import F3DASMAbaqusSimulator


class _FakeInnerSim:
    """Stand-in for :class:`AbaqusSimulator` used to record ``.run`` calls."""

    def __init__(self, working_directory: Path, results: dict):
        self.working_directory = Path(working_directory)
        self._results = results
        self.last_call: dict | None = None

    def run(
        self,
        py_file,
        function_name,
        post_py_file,
        simulation_parameters,
        submit_job,
    ):
        self.last_call = {
            "py_file": py_file,
            "function_name": function_name,
            "post_py_file": post_py_file,
            "simulation_parameters": simulation_parameters,
            "submit_job": submit_job,
        }
        sample_dir = self.working_directory / simulation_parameters["name"]
        sample_dir.mkdir(parents=True, exist_ok=True)
        with open(sample_dir / "results.pkl", "wb") as f:
            pickle.dump(self._results, f, protocol=0)


def _build_adapter(tmp_path: Path, results: dict) -> F3DASMAbaqusSimulator:
    adapter = F3DASMAbaqusSimulator(
        py_file=str(tmp_path / "pre.py"),
        post_py_file=str(tmp_path / "post.py"),
        working_directory=tmp_path,
    )
    adapter.simulator = _FakeInnerSim(
        working_directory=tmp_path, results=results
    )
    return adapter


def test_is_datagenerator_subclass():
    assert issubclass(F3DASMAbaqusSimulator, DataGenerator)


def test_working_directory_none_defaults_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    adapter = F3DASMAbaqusSimulator(py_file="pre.py")
    assert adapter.simulator.working_directory == Path(tmp_path)


def test_execute_uses_id_as_name(tmp_path: Path):
    adapter = _build_adapter(tmp_path, {"y": 42.0, "label": "ok"})

    sample = ExperimentSample(_input_data={"x0": 1.0, "x1": 2.0})
    out = adapter.execute(experiment_sample=sample, id=7)

    assert adapter.simulator.last_call["simulation_parameters"]["name"] == "7"
    assert out.output_data["y"] == 42.0
    assert out.output_data["label"] == "ok"


def test_execute_without_id_uses_default_name(tmp_path: Path):
    adapter = _build_adapter(tmp_path, {"y": 1.0})
    sample = ExperimentSample(_input_data={"x0": 1.0})

    adapter.execute(experiment_sample=sample)

    name = adapter.simulator.last_call["simulation_parameters"]["name"]
    assert name == "simulation_0"


def test_execute_respects_explicit_name_in_input(tmp_path: Path):
    adapter = _build_adapter(tmp_path, {"y": 1.0})
    sample = ExperimentSample(_input_data={"x0": 1.0, "name": "custom"})

    adapter.execute(experiment_sample=sample, id=99)

    # An explicit 'name' in the input data must NOT be overwritten by id.
    assert (
        adapter.simulator.last_call["simulation_parameters"]["name"]
        == "custom"
    )


def test_execute_scalar_results_stored_in_memory(tmp_path: Path):
    adapter = _build_adapter(
        tmp_path, {"scalar": 3.14, "array": [[1, 2], [3, 4]]}
    )
    sample = ExperimentSample(_input_data={"x0": 1.0})

    out = adapter.execute(experiment_sample=sample, id=0)

    # Scalars are stored as-is in output_data; non-scalars are stored to disk
    # via ToDiskValue and are resolved through the ``output_data`` property.
    assert out._output_data["scalar"] == 3.14
    # Non-scalar is wrapped as a ToDiskValue object (not the raw list).
    assert out._output_data["array"] is not [[1, 2], [3, 4]]


def test_execute_kwargs_forwarded_to_simulator(tmp_path: Path):
    adapter = _build_adapter(tmp_path, {"y": 1.0})
    sample = ExperimentSample(_input_data={"x0": 1.0})

    adapter.execute(experiment_sample=sample, id=0, extra_param="hello")

    sim_params = adapter.simulator.last_call["simulation_parameters"]
    assert sim_params["extra_param"] == "hello"


def test_execute_raises_when_results_missing(tmp_path: Path):
    adapter = _build_adapter(tmp_path, {"y": 1.0})
    # Replace the fake inner sim with one that does not write results.pkl.
    adapter.simulator.run = lambda **kw: None
    sample = ExperimentSample(_input_data={"x0": 1.0})

    with pytest.raises(FileNotFoundError):
        adapter.execute(experiment_sample=sample, id=0)
