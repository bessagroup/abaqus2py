"""Tests for the IO helpers in ``abaqus2py._src.io``."""

from __future__ import annotations

import pickle
import time
from pathlib import Path

import pytest

from abaqus2py._src.io import (
    DEFAULT_JOBNAME,
    FILENAME_POSTPROCESS,
    FILENAME_PREPROCESS,
    FILENAME_SIMINFO,
    create_postprocess_script,
    create_preprocess_script,
    remove_temporary_files,
    wait_until_text_verification,
    write_sim_info,
)


def test_constants_are_strings():
    assert isinstance(FILENAME_PREPROCESS, str)
    assert isinstance(FILENAME_POSTPROCESS, str)
    assert isinstance(FILENAME_SIMINFO, str)
    assert isinstance(DEFAULT_JOBNAME, str)


def test_write_sim_info_roundtrips(tmp_path: Path):
    payload = {"a": 1, "b": "two", "c": [1.0, 2.0, 3.0]}
    write_sim_info(sim_info=payload, working_dir=tmp_path)

    siminfo_path = tmp_path / f"{FILENAME_SIMINFO}.pkl"
    assert siminfo_path.exists()

    with open(siminfo_path, "rb") as f:
        assert pickle.load(f) == payload


def test_create_preprocess_script_contents(tmp_path: Path):
    python_file = tmp_path / "module.py"
    create_preprocess_script(
        working_dir=tmp_path,
        python_file=python_file,
        function_name="run_me",
    )

    script_path = tmp_path / f"{FILENAME_PREPROCESS}.py"
    assert script_path.exists()

    text = script_path.read_text()
    assert "import pickle" in text
    assert f"sys.path.extend([{repr(str(python_file.parent))}])" in text
    assert f"from {python_file.stem} import run_me" in text
    assert f"{FILENAME_SIMINFO}.pkl" in text
    assert f"os.chdir({repr(str(tmp_path))})" in text
    assert "run_me(sim_info)" in text


def test_create_postprocess_script_contents(tmp_path: Path):
    python_file = tmp_path / "post_module.py"
    odb_file = tmp_path / "job.odb"
    create_postprocess_script(
        working_dir=tmp_path,
        python_file=python_file,
        odb_file=odb_file,
        function_name="post",
    )

    script_path = tmp_path / f"{FILENAME_POSTPROCESS}.py"
    assert script_path.exists()

    text = script_path.read_text()
    assert "from abaqus import session" in text
    assert f"sys.path.extend([{repr(str(python_file.parent))}])" in text
    assert f"from {python_file.stem} import post" in text
    odb_path = odb_file.with_suffix(".odb")
    # The path is embedded with repr() so it is a valid Python string literal;
    # on Windows that doubles the backslashes, so match the repr() form rather
    # than the raw path.
    assert f"session.openOdb(name={repr(str(odb_path))})" in text
    assert "post(odb)" in text


def test_remove_temporary_files_default_extensions(tmp_path: Path):
    removed = [".log", ".lck", ".rec"]
    kept = [".inp", ".txt"]
    for ext in removed + kept:
        (tmp_path / f"file{ext}").write_text("x")

    remove_temporary_files(directory=tmp_path)

    for ext in removed:
        assert not (tmp_path / f"file{ext}").exists()
    for ext in kept:
        assert (tmp_path / f"file{ext}").exists()


def test_remove_temporary_files_custom_extensions(tmp_path: Path):
    (tmp_path / "a.foo").write_text("x")
    (tmp_path / "b.bar").write_text("x")
    (tmp_path / "c.log").write_text("x")  # should NOT be removed now

    remove_temporary_files(directory=tmp_path, file_types=[".foo"])

    assert not (tmp_path / "a.foo").exists()
    assert (tmp_path / "b.bar").exists()
    assert (tmp_path / "c.log").exists()


def test_wait_until_text_verification_success(tmp_path: Path):
    target = tmp_path / "out.log"
    target.write_text("nothing yet\nJOB TIME SUMMARY\n")

    start = time.monotonic()
    wait_until_text_verification(
        working_dir=tmp_path,
        file_extension=".log",
        text="JOB TIME SUMMARY",
        max_waiting_time=5,
    )
    assert time.monotonic() - start < 2


def test_wait_until_text_verification_timeout(tmp_path: Path):
    (tmp_path / "out.log").write_text("wrong contents")

    with pytest.raises(TimeoutError):
        wait_until_text_verification(
            working_dir=tmp_path,
            file_extension=".log",
            text="NEVER_PRESENT",
            max_waiting_time=1,
        )


def test_wait_until_text_verification_scans_all_matches(tmp_path: Path):
    # The marker lives in a file that is not the first glob match; the waiter
    # must still find it instead of only inspecting one arbitrary file.
    (tmp_path / "a.log").write_text("nothing here")
    (tmp_path / "z.log").write_text("JOB TIME SUMMARY")

    wait_until_text_verification(
        working_dir=tmp_path,
        file_extension=".log",
        text="JOB TIME SUMMARY",
        max_waiting_time=2,
    )


def test_wait_until_text_verification_failure_marker(tmp_path: Path):
    (tmp_path / "job.msg").write_text("THE ANALYSIS HAS NOT BEEN COMPLETED")

    with pytest.raises(RuntimeError, match="Abaqus reported a failure"):
        wait_until_text_verification(
            working_dir=tmp_path,
            file_extension=".msg",
            text="JOB TIME SUMMARY",
            max_waiting_time=5,
            failure_texts=["THE ANALYSIS HAS NOT BEEN COMPLETED"],
        )


def test_create_preprocess_script_handles_quote_in_path(tmp_path: Path):
    # A path containing a single quote must still produce valid Python.
    weird_dir = tmp_path / "o'clock"
    weird_dir.mkdir()
    python_file = weird_dir / "module.py"

    create_preprocess_script(
        working_dir=weird_dir,
        python_file=python_file,
        function_name="main",
    )

    text = (weird_dir / f"{FILENAME_PREPROCESS}.py").read_text()
    # Should compile without raising a SyntaxError.
    compile(text, "preprocess.py", "exec")
