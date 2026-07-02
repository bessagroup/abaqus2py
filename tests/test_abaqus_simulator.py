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
    # _submit passes the full .inp path through to abaqus_submit, which
    # derives the job name (stem) and working directory (parent) itself.
    assert Path(inp_arg) == target
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


def test_submit_does_not_change_process_cwd(recorded_abaqus, tmp_path: Path):
    """_submit routes the working directory through subprocess ``cwd=`` (see
    abaqus_submit) rather than os.chdir, so the process cwd is never touched
    and it forwards the full .inp path."""
    original = Path.cwd()
    inp = tmp_path / "job.inp"
    inp.write_text("** dummy")

    sim_mod._submit(inp_file=inp, num_cpus=1, delete_temp_files=False)

    assert Path.cwd() == original
    inp_arg, _ = recorded_abaqus["submit"][0]
    assert Path(inp_arg) == inp


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
    # Must run in the script's directory so CAE's .rec/.rpy files land in the
    # (writable) working directory, not the read-only job launch directory.
    assert recorded["kwargs"].get("cwd") == tmp_path


def test_abaqus_submit_uses_subprocess_list(monkeypatch, tmp_path: Path):
    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        recorded["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(sim_mod.subprocess, "run", fake_run)

    sim_mod.abaqus_submit(inp_file=tmp_path / "job.inp", num_cpus=2)

    assert isinstance(recorded["cmd"], list)
    assert recorded["cmd"][0] == "abaqus"
    # Submitted by job name (stem), not the full path or filename.
    assert "job=job" in recorded["cmd"]
    assert "cpus=2" in recorded["cmd"]
    assert recorded["kwargs"].get("check") is True
    # Runs in the .inp's directory so job outputs land in the writable
    # working directory, not the read-only launch directory.
    assert recorded["kwargs"].get("cwd") == tmp_path


def test_abaqus_call_retries_transient_license_error(
    monkeypatch, tmp_path: Path
):
    """A transient license failure is retried and then succeeds."""
    calls = {"n": 0}

    def flaky_run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise subprocess.CalledProcessError(
                1,
                cmd,
                stderr="ERROR 1A000060: Unable to connect to server",
            )
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(sim_mod.subprocess, "run", flaky_run)
    monkeypatch.setattr(sim_mod.time, "sleep", lambda _: None)

    # Should not raise: the third attempt succeeds.
    sim_mod.abaqus_call(tmp_path / "preprocess")
    assert calls["n"] == 3


def test_abaqus_call_raises_after_exhausting_license_retries(
    monkeypatch, tmp_path: Path
):
    """A persistent license failure raises once the retry budget is spent."""
    calls = {"n": 0}

    def always_license_error(cmd, **kwargs):
        calls["n"] += 1
        raise subprocess.CalledProcessError(
            1, cmd, stderr="Failed to startup licensing (err01): 1A000060"
        )

    monkeypatch.setattr(sim_mod.subprocess, "run", always_license_error)
    monkeypatch.setattr(sim_mod.time, "sleep", lambda _: None)
    monkeypatch.setattr(sim_mod, "ABAQUS_LICENSE_MAX_RETRIES", 2)

    with pytest.raises(subprocess.CalledProcessError):
        sim_mod.abaqus_call(tmp_path / "preprocess")
    assert calls["n"] == 3  # 1 initial attempt + 2 retries


def test_abaqus_call_does_not_retry_analysis_error(
    monkeypatch, tmp_path: Path
):
    """A non-license failure surfaces immediately, without retrying."""
    calls = {"n": 0}
    slept: list[float] = []

    def analysis_error(cmd, **kwargs):
        calls["n"] += 1
        raise subprocess.CalledProcessError(
            1, cmd, stderr="Abaqus/CAE Kernel exited with an error"
        )

    monkeypatch.setattr(sim_mod.subprocess, "run", analysis_error)
    monkeypatch.setattr(sim_mod.time, "sleep", lambda s: slept.append(s))

    with pytest.raises(subprocess.CalledProcessError):
        sim_mod.abaqus_call(tmp_path / "preprocess")
    assert calls["n"] == 1
    assert slept == []


@pytest.fixture
def submitted_run(monkeypatch, tmp_path: Path):
    """Stub the abaqus hooks for a full ``run`` and record invocations.

    ``fake_submit`` mimics a solver according to ``behavior["msg_content"]``:
    it writes a ``.log`` that has started and a ``.msg`` with the given
    content, so the two completion waits in ``run`` see real files.
    """
    calls = {"call": [], "terminate": [], "msg_content": "JOB TIME SUMMARY"}

    def fake_call(script: Path) -> None:
        calls["call"].append(Path(script))
        if script.stem == FILENAME_PREPROCESS:
            (script.parent / "job.inp").write_text("** dummy inp")

    def fake_submit(inp_file: Path, num_cpus: int) -> None:
        (inp_file.parent / "job.log").write_text(
            "Begin Analysis Input File Processor"
        )
        (inp_file.parent / "job.msg").write_text(calls["msg_content"])

    def fake_terminate(job_name: str, working_dir: Path) -> None:
        calls["terminate"].append((job_name, Path(working_dir)))

    monkeypatch.setattr(sim_mod, "abaqus_call", fake_call)
    monkeypatch.setattr(sim_mod, "abaqus_submit", fake_submit)
    monkeypatch.setattr(sim_mod, "abaqus_terminate", fake_terminate)
    return calls


def test_run_terminates_job_on_timeout(submitted_run, tmp_path: Path):
    """A completion-wait timeout must terminate the (still running) job so it
    does not keep holding license tokens, then re-raise."""
    submitted_run["msg_content"] = "solver still going, no summary"

    sim = AbaqusSimulator(working_directory=tmp_path, max_waiting_time=1)
    with pytest.raises(TimeoutError):
        sim.run(
            py_file=str(tmp_path / "user_script.py"),
            simulation_parameters={"name": "job_t"},
        )

    assert submitted_run["terminate"] == [("job", tmp_path / "job_t")]


def test_run_terminates_job_on_stall(submitted_run, tmp_path: Path):
    """With ``max_stall_time`` set, a dead job fails on the stall clock well
    before a generous ``max_waiting_time`` and is terminated."""
    submitted_run["msg_content"] = "solver still going, no summary"

    sim = AbaqusSimulator(
        working_directory=tmp_path, max_waiting_time=60, max_stall_time=1
    )
    with pytest.raises(TimeoutError, match="appears dead"):
        sim.run(
            py_file=str(tmp_path / "user_script.py"),
            simulation_parameters={"name": "job_s"},
        )

    assert submitted_run["terminate"] == [("job", tmp_path / "job_s")]


def test_run_raises_on_solver_error_lines(submitted_run, tmp_path: Path):
    """An analysis that reaches JOB TIME SUMMARY but wrote ***ERROR lines
    must fail with the solver's message, before post-processing runs."""
    submitted_run["msg_content"] = (
        " ***ERROR: INCREASE THE NUMBER OF ITERATIONS TO GET THE REQUESTED\n"
        "JOB TIME SUMMARY\n"
    )

    sim = AbaqusSimulator(working_directory=tmp_path, max_waiting_time=5)
    with pytest.raises(RuntimeError, match="INCREASE THE NUMBER"):
        sim.run(
            py_file=str(tmp_path / "user_script.py"),
            post_py_file=str(tmp_path / "post_script.py"),
            simulation_parameters={"name": "job_e"},
        )

    # Only the preprocess CAE call ran; the post script was never invoked.
    assert len(submitted_run["call"]) == 1
    assert submitted_run["terminate"] == []


def test_run_clean_job_reaches_postprocess(submitted_run, tmp_path: Path):
    """A clean .msg (summary, no error lines) proceeds to post-processing."""
    sim = AbaqusSimulator(
        working_directory=tmp_path, max_waiting_time=5, max_stall_time=5
    )
    sim.run(
        py_file=str(tmp_path / "user_script.py"),
        post_py_file=str(tmp_path / "post_script.py"),
        simulation_parameters={"name": "job_ok"},
    )

    assert len(submitted_run["call"]) == 2  # preprocess + postprocess
    assert submitted_run["terminate"] == []


def test_abaqus_terminate_never_raises(monkeypatch, tmp_path: Path):
    """Termination is best-effort cleanup on an already-failing path; a
    missing abaqus binary or non-zero exit must not mask the original error.
    """

    def missing_binary(cmd, **kwargs):
        raise FileNotFoundError("abaqus not found")

    monkeypatch.setattr(sim_mod.subprocess, "run", missing_binary)
    sim_mod.abaqus_terminate(job_name="job", working_dir=tmp_path)
