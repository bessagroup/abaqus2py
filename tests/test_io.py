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
    assert f"sys.path.extend([r'{python_file.parent}'])" in text
    assert f"from {python_file.stem} import run_me" in text
    assert f"{FILENAME_SIMINFO}.pkl" in text
    assert f"os.chdir(r'{tmp_path}')" in text
    assert "run_me(dict)" in text


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
    assert f"sys.path.extend([r'{python_file.parent}'])" in text
    assert f"from {python_file.stem} import post" in text
    assert "session.openOdb(name=r'" in text
    assert str(odb_file.with_suffix(".odb")) in text
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
