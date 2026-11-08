# Lab run needs in `deckz labs check --container`: secrets, variables, hooks

Planned 2026-11-08 from a slides session on its packaging lab
(`labs/notebooks/python/production/packaging/package-creation/hands-on-{fr,en}.ipynb`).
The goal: an automated run of that lab publishes a real package to Test PyPI and
installs it back, so the whole chain trainees go through (build, upload, index,
install) is checked, not only the build.

## Why deckz has to change

- A notebook's metadata can already ask for what its runs need (`RunNeeds`,
  `labs/gpu.py`): `variables` and `secrets`, each mapping a notebook variable
  assigned `""` on a line of its own to an environment variable (or `.env` entry),
  and a `hook`, a command of `labs.gpu.hooks` run before and after the run. slides'
  mlflow-registry demos use it (`shuuchuu.gpu: {hook: dagshub-landscape, secrets:
  {jeton: DAGSHUB_TOKEN}, variables: {nom_utilisateur: DAGSHUB_USERNAME}}`).
- Only `deckz labs gpu queue` honors it. `deckz labs check --container`
  (`labs/container.py`) sends the notebook unchanged through stdin, and `docker
  run` passes no environment: a container run can't hold a credential.
- The packaging lab needs no GPU, so renting one to publish to Test PyPI would be
  absurd. The container run is the right place: it is what a trainee's Run all
  does in a Codespace, and for a notebook with no GPU, in Colab.

## What the slides session established (verified 2026-11-08)

- Test PyPI project `thermometer-shuuchuu` (repository shuuchuu/thermometer, the
  lab's end state): 0.2.0 and 0.2.1 published. The token, `TESTPYPI_TOKEN` in
  `~/.config/deckz/.env`, is scoped to that project.
- PyPI and Test PyPI have no API to delete a release or a project (web UI only,
  with 2FA), and a version number, once used, is never usable again. So an
  automated run can't clean up after itself: each run publishes a new
  `0.2.0.dev<timestamp>` and the releases pile up (a few KB each). A `hook` has
  nothing to do for this lab; it is still worth supporting for the next lab that
  writes to a server with a reset API, as the DagsHub demos do.
- Test PyPI served a new version within about a minute, a new project only after
  a few minutes (a 404 fetched earlier stays cached by the CDN): the notebook's
  install step has to retry.
- Colab and the Codespace image set `UV_CONSTRAINT` (Colab's versions, e.g. rich
  13.9.4), which applies to a fresh virtual environment too.

## Decisions (taken with the maintainer, 2026-11-08: both as recommended)

1. **Settings and metadata names.** `RunNeeds` and its hooks are no longer GPU
   specific. Recommended: a `labs.run` group (`metadata_key: shuuchuu.run`,
   `hooks`), read by both `labs gpu` and `labs check --container`, with slides'
   `labs.gpu.hooks` and its two demos' `shuuchuu.gpu` metadata moved in the same
   landing (slides is deckz's only user). Alternative: keep `labs.gpu.*` and read
   it from the container path too, cheaper but misnamed.
2. **A need that isn't set.** `labs gpu queue` refuses the notebook. For `labs
   check --container`, which runs whole directories, recommended: run the
   notebook unfilled (its `""` lines as written, the trainee's path, which every
   lab using needs must keep working) and print a fact line, `TESTPYPI_TOKEN not
   set: ran without it`, which `is_problem` doesn't count. A `--require-needs`
   flag can refuse instead, if the maintainer wants a run that must publish.

## Phases (deckz)

Phases 1 to 4 done 2026-11-08 (branch `lab-run-needs`), as written below, with
these changes:

- `labs.gpu.metadata_key`/`hooks` are refused, the error naming their new place
  (`LabsGpuSettings`'s validator): ignoring them would have dropped the hooks
  silently. So slides' `deckz.yml` and its two demos move in the same landing (done:
  slides' `ws/lab-run-needs`, landed just before deckz's merge).
- The shared module is `labs/needs.py`; `fill` and `unknown_hook` return what's
  wrong instead of raising (the container run reports a line, `labs gpu` raises
  its `GpuRunError`), and `run_hook`/`redact` raise `LabRunNeedsError`, which
  `labs gpu` converts.
- Found while redacting: the runs truncated a failed command (`SHELL_GUARD`, 300
  characters) and a cell's error (the container runner) before the host could
  redact them, so a token cut at the boundary (a PyPI token is ~200 characters)
  would have left its prefix in clear. They are now logged whole, redacted, then
  truncated (`report_lines`, and `_shell_failure` for `labs gpu`'s `.shell`
  files). `run_in_container` redacts the whole stderr before reading it.
- A notebook whose hook is unknown, or whose set variable has no `name = ""`
  line, isn't run (`run needs: ...`, then `execution: not run`). An opening hook
  that fails stops the run; a closing one that fails is a problem line.
- Trial (slides worktree, scratch environment with this deckz, the real
  `TESTPYPI_TOKEN`, a test notebook that never sends it): filled, an unset
  variable's fact line, the token redacted from a failed `!false --token
  {jeton_ci}` and from a `ValueError` (no `pypi-AgE` in the report nor in
  stderr), the hook run before and after; without `--container`, the fact line
  and no hook. `labs gpu pass --dry-run` on the mlflow-registry demo, unchanged.

### 1. Share `RunNeeds`

- Move `RunNeeds`, `run_needs`, `_fill_variables`, `_redact` and `REDACTED` from
  `labs/gpu.py` to a module of their own (e.g. `labs/needs.py`), with the hook
  runner (`_run_hook` minus its GPU state). `gpu.py` and `outputs.py` import them
  from there; behavior unchanged. `tests/test_labs_gpu.py` and
  `tests/test_labs_outputs.py` pass as they are.
- Settings as decided in 1. above (`configuring/settings.py`, with docstrings that
  name both commands).

### 2. Fill and redact in the container run

- `check_notebook` (`labs/execution.py`) reads the notebook's needs when given a
  container, and `run_in_container` gets the filled copy. The values travel only
  in the notebook sent through stdin, as today: never `docker run -e` or an
  argument, which `ps` and `docker inspect` would show.
- Every line `run_in_container` yields goes through `_redact`: a failed shell
  command's line repeats the command (`uv publish --token {jeton}` once IPython
  expanded it), and a traceback can quote a value.
- The run without `--container` (`labs.execution`'s runner) skips the shell
  commands that matter here: fill nothing there, and say so in the fact line if a
  notebook has needs.
- Hooks: run before the notebook and after it, in a `finally` (a failed or timed
  out run still gets its closing hook). No holding logic: container runs are
  sequential in one process.
- Tests (`tests/test_labs_container.py`, no Docker: the runner source and the
  report lines): a filled `""` line, an unset need's fact line, a value redacted
  from a failed shell command's line and from a traceback, both hooks run around a
  failing run.

### 3. Recognize PyPI tokens

- `labs/secrets.py`'s `_TOKEN_FORMATS` has no PyPI token: add `PyPI token`,
  `\bpypi-AgE[A-Za-z0-9_-]{50,}` (PyPI and Test PyPI tokens are macaroons whose
  base64 starts `AgE`). Test in `tests/test_labs_secrets.py`. `lab-secrets` and
  `labs publish` then catch a token pasted into the packaging lab.

### 4. Docs, then merge

- `docs/guide/labs-and-videos.md`: what a notebook's run needs are, which commands
  honor them, how an unset one behaves, where values come from (`.env`), that
  outputs never keep them.
- `docs/architecture/` (the page covering `labs`): the shared module.
- Work in a worktree (`../deckz-lab-run-needs`), as the root `CLAUDE.md` says. Try
  it on slides from a scratch environment with the worktree's deckz (phase 5's
  notebook, or a copy of it), then tell the running slides sessions before merging:
  `labs check --container`'s behavior changes (`ListAgents`, `SendMessage`).

## Phase 5 (slides, once deckz is merged): next

The metadata and hooks move is done (above); what's left is the packaging lab.

In a slides worktree, `labs/notebooks/python/production/packaging/package-creation/`
(fr first, then en; the code cells must match up to the names: `lab-pairs`):

- Metadata: `shuuchuu.run` (or the name decided) `{secrets: {jeton_ci:
  TESTPYPI_TOKEN}}`, and the same move for the two mlflow-registry demos and
  `deckz.yml`'s hooks if 1. renames them.
- Step 8's solution: a `jeton_ci = ""` line, commented for trainees (filled only
  by the lab's automated runs). When it is set, the solution does in code what a
  trainee does by hand: project `thermometer-shuuchuu` with `module-name`, the
  `testpypi` index, version `0.2.0.dev<UTC timestamp>` (`uv version`), an empty
  `dist/`, `uv build`, `uv publish --index testpypi --token {jeton_ci}`. When it
  isn't, nothing changes (`PUBLIER`/`PUBLISH` and `getpass`, as today).
- Step 9's solution: with `jeton_ci` set, install exactly the version just
  published (`thermometer-shuuchuu==<that version>`, which also lets uv take a
  pre-release), with a retry of a few minutes (IPython sets `_exit_code` after a
  `!` line). Without it, as today: the trainee's package, or the reference 0.2.1.
- Run it: `uv run deckz labs check --container --timeout 900` on the lab, with
  `TESTPYPI_TOKEN` in `~/.config/deckz/.env`; the dev version then shows on
  https://test.pypi.org/project/thermometer-shuuchuu/#history. Check that no
  output, report line or stored file holds the token (`grep -c` on the prefix,
  never print it).
- `labs/README.md`: the lab publishes for real when the token is set, which token
  (scoped to `thermometer-shuuchuu`), and that the dev releases pile up (delete
  them from the web UI now and then, if ever).
- Publishing the labs and pushing are the maintainer's.
