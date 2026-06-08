# abaqus2py — Core Library Review

A review of the shipped core of `abaqus2py` (`src/abaqus2py/_src/`):
`abaqus_simulator.py`, `io.py`, `f3dasm_adapter.py`. The package drives ABAQUS
FEM simulations by shelling out to the `abaqus` CLI via `os.system`. Because
`abaqus job=...` submits asynchronously, completion is detected by **polling a
result file for a marker string** (`wait_until_text_verification`). The f3dasm
adapter can evaluate samples in parallel.

Each item lists `file:line`, the problem, a suggested fix, and a confidence
level. Findings are grouped by severity; speculative items are marked
**[flagged]**. This document is intended to drive a later implementation pass —
no source code has been changed.

---

## High severity

### H1. `run(submit_job=False)` still waits for files that never appear
`abaqus_simulator.py:253-273`

The two `wait_until_text_verification` calls sit **outside** the `if submit_job:`
block. With `submit_job=False` no job is submitted, so the `.log`/`.msg` files
are never created and both waits run to `max_waiting_time` and then raise
`TimeoutError`. The `submit_job=False` path is effectively broken.

- **Fix:** move both `wait_until_text_verification` calls (and arguably the
  `_postprocess` call, which needs an `.odb`) inside `if submit_job:`.
- **Confidence:** High. Note the existing test `test_run_without_submit`
  monkeypatches the waiter, so it masks this bug rather than catching it.

### H2. Stale result files cause false "job complete" / wrong `.inp`
`io.py:194,199` and `abaqus_simulator.py:371-376`

`wait_until_text_verification` scans `working_dir.glob("*{ext}")` and inspects
only the **first** match (`.__next__()`), with no freshness check. If a prior
run left a `.msg` containing `"JOB TIME SUMMARY"` (or a `.log` with the start
marker) in the same directory, the wait returns **immediately** — before the
new job has even finished — and post-processing runs on stale output.

Same root cause in `_preprocess`: `working_dir.glob("*.inp").__next__()` returns
an arbitrary/stale `.inp` when more than one exists.

- **Fix options:** clear known temp/result files at the start of `_preprocess`
  (or before submit); track the expected job stem and match the file by name
  rather than "first glob hit"; and/or record submit time and require the file
  to be newer. At minimum, raise if multiple `.inp` files are present instead
  of silently picking one.
- **Confidence:** High that the first-match + stale-file behavior is wrong;
  severity depends on whether directories are reused across runs (they are, in
  `run()`'s per-`name` subdirectories).

### H3. No return-code check and no shell-quoting on `os.system`
`abaqus_simulator.py:52,66`

```python
os.system(f"abaqus cae noGUI={script.with_suffix('.py')} -mesa")
os.system(f"abaqus job={inp_file} cpus={num_cpus}")
```

- Exit status is ignored, so an ABAQUS launch/licensing/syntax failure passes
  silently and surfaces later as a confusing `TimeoutError` (H1) or
  `FileNotFoundError` (no `.inp`).
- Paths are interpolated unquoted: a path with a **space** splits into multiple
  args; shell metacharacters (`;`, backtick, `$()`) break or inject.
- **Fix:** switch to `subprocess.run([...], check=True)` with an argument list
  (no shell), or at least check the return code and `shlex.quote` the paths.
- **Confidence:** High.

---

## Medium severity

### M1. `_submit` doesn't restore cwd on failure; `os.chdir` is process-global
`abaqus_simulator.py:297-307`

`_submit` does `os.chdir(inp_file.parent)`, calls `abaqus_submit`, then
`os.chdir(cwd)`. If `abaqus_submit` (or `remove_temporary_files`) raises, the
cwd is never restored and all subsequent work runs in the wrong directory.

- **[flagged]** Additionally, `os.chdir` mutates **process-global** state. If
  f3dasm's parallel `mode` uses threads, concurrent `_submit` calls race on the
  cwd. (If parallelism is process/HPC-job based — as in `studies/.../main.py` —
  this is moot. Confirm f3dasm's executor model before treating as a live bug.)
- **Fix:** wrap in `try/finally`; better, avoid `chdir` entirely by passing a
  working directory to the abaqus invocation, which also fixes the race.
- **Confidence:** High for the exception-safety issue; flagged/conditional for
  the threading race.

### M2. No detection of failed / aborted ABAQUS analyses
`io.py:160-214`

`wait_until_text_verification` only looks for success markers. ABAQUS writes
`"JOB TIME SUMMARY"` even when an analysis **aborts with errors**, so a failed
run can be treated as success and post-processed; conversely a job that dies
without writing the marker just burns the full timeout with no diagnostic.

- **Fix:** also scan for error/abort markers (e.g. `.sta` "THE ANALYSIS HAS NOT
  BEEN COMPLETED", `.msg`/`.dat` `***ERROR`) and raise a descriptive error.
- **Confidence:** High that failures are undetected; the exact markers need
  verification against the ABAQUS version in use.

### M3. Single `Path` argument breaks `submit()` / `postprocess()`
`abaqus_simulator.py:162,191`

Both methods special-case only `str` to wrap a scalar in a list
(`if isinstance(inp_files, str)`). Passing a single `Path` (natural, since the
library is Path-centric internally) falls through and the code iterates the
`Path` — which raises `TypeError`.

- **Fix:** `isinstance(x, (str, Path))`.
- **Confidence:** High that a single `Path` fails; medium on how often callers
  do this.

### M4. Generated scripts embed paths as raw strings — quote/backslash unsafe
`io.py:76,78,80,110,112,113`

Paths are written into generated Python as `r'{path}'`. A path containing a
single quote produces a `SyntaxError` in the generated script; on Windows a
path ending in a backslash makes `r'...\'` unterminated.

- **Fix:** use `repr(str(path))` instead of hand-built `r'...'` literals.
- **Confidence:** Medium (edge-case paths, but a silent, hard-to-debug failure
  when hit). Also `dict = pickle.load(f)` in the generated preprocess script
  shadows the builtin — harmless but worth renaming.

### M5. f3dasm scalar/disk split misclassifies numpy scalars
`f3dasm_adapter.py:162-166`

`isinstance(value, int | float | str)` is False for numpy scalars
(`np.float64`, `np.int64`), so scalar results from a typical postprocess script
get written **to disk** instead of stored in memory.

- **Fix:** broaden the check, e.g. `np.isscalar(value)` (excluding `ndarray`),
  or include `np.integer | np.floating | bool`.
- **Confidence:** Medium (behavioral inefficiency, not a crash).

---

## Low severity / cleanup

### L1. Shared `function_name` for pre- and post-processing — flexibility limit
`abaqus_simulator.py:206,280`; `f3dasm_adapter.py:101,146`

`run()` and the adapter use a single `function_name` for both the preprocess
and postprocess scripts. This is **not** a runtime bug in normal use — pre and
post live in separate files (see `studies/.../main.py`), so each can define its
own `main(dict)` / `main(odb)`. But you cannot give them *different* names in a
single `run()` call.

- **Fix (optional):** add an optional `post_function_name` (default falling back
  to `function_name`).
- **Confidence:** High that it's a limitation; low priority.

### L2. Type annotation omits `None` default
`abaqus_simulator.py:112-113,208-209`

`simulation_parameters: Iterable[dict[str, Any]] | dict[str, Any] = None` — the
default is `None` but the type doesn't allow it. Add `| None` / `Optional[...]`.

### L3. Duplicated name-resolution logic
`abaqus_simulator.py:138-143` and `237-243`

The "use `sim_params['name']` else `f'{DEFAULT_JOBNAME}_{index}'`" block is
duplicated in `preprocess()` and `run()`. Extract a small helper.

### L4. Dead `success` flag in `wait_until_text_verification`
`io.py:187,209` — the function returns on success inside the loop, so `success`
is always False where it's checked. Simplify to just raise after the loop.

---

## Test coverage gaps

Current tests stub `abaqus_call`/`abaqus_submit`, so several real paths are
never exercised:

- **submit_job=False (H1):** the only `run()` test monkeypatches the waiter;
  add a test that does **not** patch it and asserts the waits are skipped.
- **Stale files (H2):** pre-seed a `.msg`/`.inp` from a "previous run" and
  assert the new run doesn't falsely complete / doesn't pick the stale `.inp`.
- **`delete_temp_files` / `delete_odb`:** no test asserts files are actually
  removed (`abaqus_simulator.py:311-312,417-418`).
- **Iterable-of-dicts `simulation_parameters`:** only single-dict is tested;
  cover multi-job loops and the default-naming branch.
- **Single `Path` arg (M3):** `submit(Path(...))` / `postprocess(odb_files=Path)`.
- **`_submit` cwd restoration (M1):** make `abaqus_submit` raise and assert cwd
  is restored.
- **Analysis-failure detection (M2):** `.msg` with `JOB TIME SUMMARY` but also
  error markers should not be treated as clean success.
- **`_preprocess` missing-`.inp` branch:** stub `abaqus_call` to not create an
  `.inp` and assert the `FileNotFoundError` (`abaqus_simulator.py:371-376`).

---

## Suggested fix ordering

1. **H1** (one-line scope fix) and **H3** (subprocess + return-code) — biggest
   correctness/robustness wins, low risk.
2. **H2** + **M2** together — they share the "trust the result file" root
   cause; design a clear pre-run cleanup + freshness/marker strategy.
3. **M1, M3, M4, M5** — independent, small, well-scoped.
4. **L1–L4** cleanups alongside the above.
5. Backfill the test gaps as each fix lands.

## Verification

After implementing, run `make test` (or `uv run pytest`) and `make lint`. Add
the new tests listed above; the H1 and stale-file tests must *fail before* the
fix and pass after.
