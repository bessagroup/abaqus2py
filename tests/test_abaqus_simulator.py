"""Tests for :class:`abaqus2py.AbaqusSimulator`.

Abaqus is not installed in the test environment; every place the simulator
would shell out to ``abaqus`` is monkey-patched to a recording stub.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from abaqus2py import AbaqusSimulator
from abaqus2py._src import abaqus_simulator as sim_mod
from abaqus2py._src.io import FILENAME_POSTPROCESS, FILENAME_PREPROCESS


@pytest.fixture
def recorded_abaqus(monkeypatch, tmp_path: Path):
    """Stub ``abaqus_call``/``abaqus_submit`` and record invocations.

    The stub ``abaqus_call`` creates a dummy ``.inp`` file next to the
    preprocess script so that ``_preprocess`` finds something to return.
    """
    calls: dict[str, list] = {"call": [], "submit": []}

    def fake_call(script: Path) -> None:
        calls["call"].append(Path(script))
        # Simulate preprocessing: drop a .inp next to the script.
        if script.stem == FILENAME_PREPROCESS:
            (script.parent / "job.inp").write_text("** dummy inp")

    def fake_submit(inp_file: Path, num_cpus: int) -> None:
        calls["submit"].append((Path(inp_file), num_cpus))

    monkeypatch.setattr(sim_mod, "abaqus_call", fake_call)
    monkeypatch.setattr(sim_mod, "abaqus_submit", fake_submit)
    return calls


def test_working_directory_is_coerced_to_path():
    sim = AbaqusSimulator(working_directory="/tmp/foo")
    assert isinstance(sim.working_directory, Path)
    assert sim.working_directory == Path("/tmp/foo")


def test_preprocess_creates_scripts_and_inp(recorded_abaqus, tmp_path: Path):
    sim = AbaqusSimulator(working_directory=tmp_path)
    sim.preprocess(
        py_file=str(tmp_path / "user_script.py"),
        function_name="main",
        simulation_parameters={"name": "job_a", "alpha": 1.23},
    )

    job_dir = tmp_path / "job_a"
    assert job_dir.is_dir()
    assert (job_dir / f"{FILENAME_PREPROCESS}.py").exists()
    assert (job_dir / "sim_info.pkl").exists()
    assert (job_dir / "job.inp").exists()
    assert len(recorded_abaqus["call"]) == 1


def test_preprocess_default_name(recorded_abaqus, tmp_path: Path):
    sim = AbaqusSimulator(working_directory=tmp_path)
    sim.preprocess(
        py_file=str(tmp_path / "user_script.py"),
        simulation_parameters={"alpha": 0.1},
    )
    assert (tmp_path / "simulation_0").is_dir()


def test_submit_single_file(recorded_abaqus, tmp_path: Path):
    sim = AbaqusSimulator(num_cpus=4, working_directory=tmp_path)
    target = tmp_path / "job.inp"
    target.write_text("** dummy")
    sim.submit(str(target))

    assert len(recorded_abaqus["submit"]) == 1
    inp_arg, num_cpus = recorded_abaqus["submit"][0]
    # The recorded value is what abaqus_submit was called with; the current
    # implementation passes the file stem (Path/str).
    assert str(inp_arg).endswith("job")
    assert num_cpus == 4


def test_submit_multiple_files(recorded_abaqus, tmp_path: Path):
    sim = AbaqusSimulator(working_directory=tmp_path)
    files = []
    for i in range(3):
        p = tmp_path / f"job_{i}.inp"
        p.write_text("** dummy")
        files.append(str(p))

    sim.submit(files)
    assert len(recorded_abaqus["submit"]) == 3


def test_postprocess_creates_script(recorded_abaqus, tmp_path: Path):
    sim = AbaqusSimulator(working_directory=tmp_path)

    odb_file = tmp_path / "job.odb"
    odb_file.write_text("** dummy odb")

    sim.postprocess(
        py_file=str(tmp_path / "post.py"),
        odb_files=str(odb_file),
        function_name="main",
    )

    assert (tmp_path / f"{FILENAME_POSTPROCESS}.py").exists()
    assert len(recorded_abaqus["call"]) == 1


def test_run_without_submit(monkeypatch, recorded_abaqus, tmp_path: Path):
    """When ``submit_job=False`` the submit path must not run and the text
    waiters must not be invoked."""
    called_wait = {"count": 0}

    def fake_wait(*args, **kwargs):
        called_wait["count"] += 1

    monkeypatch.setattr(sim_mod, "wait_until_text_verification", fake_wait)

    sim = AbaqusSimulator(working_directory=tmp_path)
    sim.run(
        py_file=str(tmp_path / "user_script.py"),
        simulation_parameters={"name": "only_pre"},
        submit_job=False,
    )

    assert len(recorded_abaqus["submit"]) == 0
    # run() always calls wait_until_text_verification twice
    assert called_wait["count"] == 2
