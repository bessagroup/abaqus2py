"""Tests for :class:`abaqus2py.AbaqusSimulator`.

Abaqus is not installed in the test environment; every place the simulator
would shell out to ``abaqus`` is monkey-patched to a recording stub.
"""

from __future__ import annotations

import subprocess
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
    """When ``submit_job=False`` no job is submitted and the text waiters must
    NOT be invoked (otherwise they would poll for files that never appear and
    time out)."""
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
    # The waiters must be skipped entirely when no job is submitted.
    assert called_wait["count"] == 0


def test_submit_single_path_object(recorded_abaqus, tmp_path: Path):
    """A single ``Path`` (not just ``str``) must be accepted and not iterated
    character-by-character."""
    sim = AbaqusSimulator(working_directory=tmp_path)
    target = tmp_path / "job.inp"
    target.write_text("** dummy")

    sim.submit(target)  # pass a Path, not a str

    assert len(recorded_abaqus["submit"]) == 1


def test_postprocess_single_path_object(recorded_abaqus, tmp_path: Path):
    sim = AbaqusSimulator(working_directory=tmp_path)
    odb_file = tmp_path / "job.odb"
    odb_file.write_text("** dummy odb")

    sim.postprocess(py_file=tmp_path / "post.py", odb_files=odb_file)

    assert (tmp_path / f"{FILENAME_POSTPROCESS}.py").exists()
    assert len(recorded_abaqus["call"]) == 1


def test_preprocess_multiple_simulation_parameters(
    recorded_abaqus, tmp_path: Path
):
    sim = AbaqusSimulator(working_directory=tmp_path)
    sim.preprocess(
        py_file=str(tmp_path / "user_script.py"),
        simulation_parameters=[{"name": "job_a"}, {"alpha": 1.0}],
    )

    assert (tmp_path / "job_a").is_dir()
    # Second dict has no 'name' -> default naming using its index.
    assert (tmp_path / "simulation_1").is_dir()
    assert len(recorded_abaqus["call"]) == 2


def test_preprocess_raises_when_no_inp_created(monkeypatch, tmp_path: Path):
    """If the Abaqus call produces no .inp, a FileNotFoundError is raised."""

    def call_without_inp(script: Path) -> None:
        pass  # deliberately create nothing

    monkeypatch.setattr(sim_mod, "abaqus_call", call_without_inp)

    sim = AbaqusSimulator(working_directory=tmp_path)
    with pytest.raises(FileNotFoundError):
        sim.preprocess(
            py_file=str(tmp_path / "user_script.py"),
            simulation_parameters={"name": "job"},
        )


def test_preprocess_clears_stale_inp(monkeypatch, tmp_path: Path):
    """A stale .inp from a previous run must be cleared so the returned path
    is the one created by the current call."""
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "stale.inp").write_text("** old run")

    created: dict[str, Path] = {}

    def call_creates_fresh(script: Path) -> None:
        if script.stem == FILENAME_PREPROCESS:
            fresh = script.parent / "fresh.inp"
            fresh.write_text("** new run")
            created["inp"] = fresh

    monkeypatch.setattr(sim_mod, "abaqus_call", call_creates_fresh)

    inp = sim_mod._preprocess(
        delete_temp_files=False,
        py_file=Path(tmp_path / "user_script.py"),
        working_dir=job_dir,
        function_name="main",
        name="job",
    )

    assert inp == created["inp"]
    assert not (job_dir / "stale.inp").exists()


def test_preprocess_raises_on_multiple_inp(monkeypatch, tmp_path: Path):
    def call_creates_two(script: Path) -> None:
        if script.stem == FILENAME_PREPROCESS:
            (script.parent / "a.inp").write_text("** a")
            (script.parent / "b.inp").write_text("** b")

    monkeypatch.setattr(sim_mod, "abaqus_call", call_creates_two)

    with pytest.raises(RuntimeError, match="single .inp"):
        sim_mod._preprocess(
            delete_temp_files=False,
            py_file=Path(tmp_path / "user_script.py"),
            working_dir=tmp_path / "job",
            function_name="main",
            name="job",
        )


def test_delete_temp_files_removes_artifacts(recorded_abaqus, tmp_path: Path):
    sim = AbaqusSimulator(working_directory=tmp_path, delete_temp_files=True)
    sim.preprocess(
        py_file=str(tmp_path / "user_script.py"),
        simulation_parameters={"name": "job"},
    )

    job_dir = tmp_path / "job"
    # The generated preprocess script and sim_info pickle are cleaned up.
    assert not (job_dir / f"{FILENAME_PREPROCESS}.py").exists()
    assert not (job_dir / "sim_info.pkl").exists()


def test_delete_odb_removes_odb(recorded_abaqus, tmp_path: Path):
    sim = AbaqusSimulator(working_directory=tmp_path, delete_odb=True)
    odb_file = tmp_path / "job.odb"
    odb_file.write_text("** dummy odb")

    sim.postprocess(py_file=str(tmp_path / "post.py"), odb_files=str(odb_file))

    assert not odb_file.exists()


def test_submit_restores_cwd_on_exception(monkeypatch, tmp_path: Path):
    """If abaqus_submit raises, _submit must still restore the cwd."""

    def boom(inp_file, num_cpus):
        raise RuntimeError("abaqus blew up")

    monkeypatch.setattr(sim_mod, "abaqus_submit", boom)

    original = Path.cwd()
    inp = tmp_path / "job.inp"
    inp.write_text("** dummy")

    with pytest.raises(RuntimeError):
        sim_mod._submit(inp_file=inp, num_cpus=1, delete_temp_files=False)

    assert Path.cwd() == original


def test_abaqus_call_uses_subprocess_list(monkeypatch, tmp_path: Path):
    """abaqus_call must invoke subprocess.run with an argument list (no shell)
    and check=True so failures surface."""
    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        recorded["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(sim_mod.subprocess, "run", fake_run)

    sim_mod.abaqus_call(tmp_path / "preprocess")

    assert isinstance(recorded["cmd"], list)
    assert recorded["cmd"][0] == "abaqus"
    assert recorded["kwargs"].get("check") is True


def test_abaqus_submit_uses_subprocess_list(monkeypatch, tmp_path: Path):
    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        recorded["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(sim_mod.subprocess, "run", fake_run)

    sim_mod.abaqus_submit(inp_file=Path("job"), num_cpus=2)

    assert isinstance(recorded["cmd"], list)
    assert recorded["cmd"][0] == "abaqus"
    assert "job=job" in recorded["cmd"]
    assert "cpus=2" in recorded["cmd"]
    assert recorded["kwargs"].get("check") is True
