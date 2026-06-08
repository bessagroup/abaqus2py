# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`abaqus2py` is a thin Python interface for driving ABAQUS finite-element
simulations from regular Python function calls. It shells out to the `abaqus`
CLI (`abaqus cae noGUI=...`, `abaqus job=...`); ABAQUS itself is **not** a
Python dependency and is not present in the dev/test environment.

The public API is just two classes (see `src/abaqus2py/__init__.py`):
- `AbaqusSimulator` — the standalone driver.
- `F3DASMAbaqusSimulator` — an `f3dasm.DataGenerator` adapter for running
  simulations over an `f3dasm.ExperimentData`.

## Commands

This project is `uv`-managed. `f3dasm` is sourced as an editable local
dependency from `/workspace/f3dasm` (see `[tool.uv.sources]` in
`pyproject.toml`).

```bash
make test          # run all tests (pytest)
make lint          # ruff check (line-length 79)
make build         # build distribution (python -m build)
make docs          # mkdocs build

uv run pytest tests/test_io.py::test_name   # run a single test
uv run ruff check --fix                      # autofix lint
```

`pyproject.toml` sets `pythonpath = ["src"]` and `testpaths = ["tests"]`, so
tests import `abaqus2py` directly without an install step. Note `tests/` and
`scripts/` are excluded from ruff lint.

## Architecture

All implementation lives under `src/abaqus2py/_src/` (the public package
re-exports from there). Three modules, each a layer:

1. **`io.py`** — pure filesystem/codegen primitives, no ABAQUS knowledge.
   - `create_preprocess_script` / `create_postprocess_script` **generate
     Python scripts on disk** that ABAQUS will later execute in its own
     interpreter. These generated scripts `sys.path`-inject the user's
     `py_file` directory, import a named function (default `main`), and call
     it. The *preprocess* script passes a `dict` of simulation parameters
     (unpickled from `sim_info.pkl`, written with `protocol=0` for Python-2
     compatibility with ABAQUS's interpreter); the *postprocess* script passes
     an opened `odb` object.
   - `wait_until_text_verification` is the synchronization mechanism: because
     `abaqus` calls are fire-and-forget via `os.system`, completion is
     detected by **polling a result file for a marker string** (e.g.
     `"JOB TIME SUMMARY"` in the `.msg` file), with a `max_waiting_time`
     timeout. This is the "workaround" referenced throughout the code.
   - Module-level filename constants (`FILENAME_PREPROCESS = "preprocess"`,
     etc.) define the on-disk contract between layers.

2. **`abaqus_simulator.py`** — the `AbaqusSimulator` dataclass orchestrating
   the lifecycle: `preprocess` → `submit` → `postprocess`, plus a combined
   `run`. The only two functions that actually invoke ABAQUS are
   `abaqus_call` (CAE/noGUI) and `abaqus_submit` (job submission) — both plain
   `os.system` wrappers; tests monkeypatch these to avoid needing ABAQUS.
   Each simulation gets its own sub-directory under `working_directory`, named
   from the `name` key in the parameter dict (falling back to
   `simulation_<index>`). `submit`/`preprocess`/`postprocess` all accept
   either a single value or an iterable.

3. **`f3dasm_adapter.py`** — `F3DASMAbaqusSimulator(DataGenerator)` wraps an
   `AbaqusSimulator`. Its `execute` turns one `ExperimentSample` into a
   parameter dict, runs the full pipeline, then reads back `results.pkl`
   (written by the user's postprocess function) with
   `encoding="latin1"`/`fix_imports=True` for Python-2 pickle compatibility.
   Scalar results are stored in-memory; everything else is stored to disk.
   **Callers must invoke `.call(..., pass_id=True)`** so f3dasm forwards the
   job index as `id`, which becomes the per-sample sub-directory name.

### The user-script contract

A user of this library supplies their own ABAQUS modeling scripts (see
`scripts/supercompressible_*.py`). A preprocess script defines a function
(default name `main`) taking a single `dict` and producing a `.inp` file in
the cwd; a postprocess script defines a function taking an opened `odb` and
writing `results.pkl`. `abaqus2py` only generates the glue that calls these.

## Studies

`studies/fragile_becomes_supercompressible/` is a full worked example
(reproducing Bessa et al. 2019) wiring `F3DASMAbaqusSimulator` into a
Hydra-configured, HPC-oriented two-stage (linear-buckle → Riks) f3dasm
workflow. Read `studies/.../main.py` for the canonical end-to-end usage
pattern.

## Conventions

- Python ≥ 3.11; type hints throughout; `from __future__ import annotations`.
- Logging goes through the `"abaqus2py"` logger (debug-level traces of every
  pre/submit/post step).
- Source files carry a Bessa-group authorship/credits header block; match it
  when adding modules.
