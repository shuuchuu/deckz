"""Execute every code cell of a notebook in order, in a throwaway directory.

Mirrors Colab's handling of shell lines (`!cmd`) and the common magics
(`%%writefile`, `%%bash`, `%time`), reporting which cells raise, in order.
Never runs a lab's own git/pip/publish commands: only a small allow-list of
harmless data-fetch shell commands run, plus the repo's standard dataset
fetch script, plus a script the notebook itself wrote with `%%writefile`.
"""

import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .inspecting import roles
from .notebook import cell_source

if TYPE_CHECKING:
    from .container import Container

EXEC_TIMEOUT = 300

# Events go to stderr behind this marker: a library may print lines of its own there
# (Lightning's `[rank: 0] Seed set to 0`, Optuna's `[I 2026-...] Trial ...`).
EVENT = "\x1eQA "

# Run by a real kernel at startup (`--IPKernelApp.exec_files`), for the runners
# using one (`labs.container`, `labs.gpu`): a failing `!cmd` (or `%pip`) never
# raises, it only sets `_exit_code`, and the cell goes on, as in Colab. So each
# failure is appended as `[exit_code, cmd]` to a JSON-lines log the runner reads
# after each cell. IPython's `system_piped`, and ipykernel's override, both call
# the `system` their module imported: wrapping it there sees every shell line,
# `{var}` already expanded, on IPython 7 (Colab's), which has no
# `system_raise_on_error`. Colab's own shell (`google.colab._shell`, which its
# runtime image starts) runs them through `_system_commands._run_command`
# instead, returning a result with a `returncode`; also called by `x = !cmd`
# there. Defined in a function deleted afterwards, so the notebook's namespace is
# left as it was.
SHELL_GUARD = r"""
def __deckz_shell_guard(log):
    import importlib, json

    def guard(run, exit_code):
        def guarded(cmd, *args, **kwargs):
            result = run(cmd, *args, **kwargs)
            code = exit_code(result)
            if code:
                with open(log, "a") as f:
                    f.write(json.dumps([code, str(cmd)[:300]]) + "\n")
            return result

        guarded.__deckz_guard__ = True
        return guarded

    for name, function, exit_code in (
        ("IPython.core.interactiveshell", "system", lambda code: code),
        ("ipykernel.zmqshell", "system", lambda code: code),
        (
            "google.colab._system_commands",
            "_run_command",
            lambda result: getattr(result, "returncode", 0),
        ),
    ):
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        run = getattr(module, function, None)
        if run is not None and not getattr(run, "__deckz_guard__", False):
            setattr(module, function, guard(run, exit_code))


__deckz_shell_guard(__SHELL_LOG__)
del __deckz_shell_guard
"""


def shell_guard(log: str) -> str:
    """`SHELL_GUARD`, appending each failed shell command to `log`.

    Returns:
        Python source, for `--IPKernelApp.exec_files`.
    """
    return SHELL_GUARD.replace("__SHELL_LOG__", repr(log))


# Run before the first cell for `--smoke` (the local runner `exec`s it, `labs.container`
# prepends it as a cell): every Lightning Trainer capped to one short epoch. Lightning
# may not be importable yet, a lab installing it in its first cells (`!pip install
# lightning`, which a container runs): an import hook then caps it when the notebook
# first imports it. Defined in a function deleted afterwards, as `SHELL_GUARD`.
SMOKE = r"""
def __deckz_smoke():
    import importlib.abc, sys

    caps = {"max_epochs": 1, "limit_train_batches": 3, "limit_val_batches": 2}
    names = ("lightning", "pytorch_lightning")

    def cap(module):
        trainer = getattr(module, "Trainer", None)
        if trainer is None or getattr(trainer, "_deckz_capped", False):
            return
        init = trainer.__init__

        def capped(self, *args, **kwargs):
            kwargs.pop("max_steps", None)
            init(self, *args, **{**kwargs, **caps})

        trainer.__init__ = capped
        trainer._deckz_capped = True

    class CapOnImport(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            if fullname not in names:
                return None
            for finder in sys.meta_path:
                if finder is self or not hasattr(finder, "find_spec"):
                    continue
                spec = finder.find_spec(fullname, path, target)
                if spec is not None and spec.loader is not None:
                    exec_module = spec.loader.exec_module

                    def exec_and_cap(module):
                        exec_module(module)
                        cap(module)

                    spec.loader.exec_module = exec_and_cap
                    return spec
            return None

    for name in names:
        if name in sys.modules:
            cap(sys.modules[name])
    sys.meta_path.insert(0, CapOnImport())


__deckz_smoke()
del __deckz_smoke
"""


_GHSPARSE = r"https://github\.com/shuuchuu/datasets/raw/refs/heads/main/ghsparse\.sh"
DATASET_FETCH = re.compile(
    rf"wget -q {_GHSPARSE} -O /tmp/ghsparse\.sh && bash /tmp/ghsparse\.sh [\w.-]+"
    # The older form: `bash` exits 0 when `wget` fails (it reads an empty script),
    # and dash, Colab's `sh`, has no `pipefail`, so the failure showed a cell later.
    rf"|wget -qO- {_GHSPARSE} \| bash -s [\w.-]+"
)
"""The repo's standard dataset fetch (see labs/README.md), exactly: the local runner's
`bash` runs nothing else."""

RUNNER = r"""
import ast, asyncio, builtins, inspect, json, re, shlex, subprocess, sys

EVENT = "\x1eQA "
# Shell lines (`!cmd`, `%%bash`) run only if every command is a harmless data fetch:
# a lab may `uv publish`, `pip install` or `git push`, which a QA run must never do.
SAFE_SHELL = {
    "wget", "curl", "unzip", "tar", "gunzip", "ls",
    "cat", "head", "mkdir", "cp", "mv", "echo",
}
DATASET_FETCH = re.compile(__DATASET_FETCH__)
# Scripts the notebook itself wrote with `%%writefile`, which `python` and
# `torchrun` may run.
written = set()
# The cell running, which a failed shell command is reported in.
running = [-1]


def emit(*event):
    print(EVENT + json.dumps(event), file=sys.__stderr__, flush=True)


class NeedsInput(Exception):
    pass


def no_input(*a, **k):
    raise NeedsInput("cell calls input() or getpass(), not run past it")


def written_script(cmd):
    # `python script.py` / `torchrun --opt=x script.py`, script written by the
    # notebook, nothing chained: the command to run, with this interpreter.
    if re.search(r"[|;&<>`$]", cmd):
        return None
    words = shlex.split(cmd)
    if not words or words[0] not in {"python", "python3", "torchrun"}:
        return None
    scripts = [w for w in words[1:] if not w.startswith("-")]
    if len(scripts) != 1 or scripts[0] not in written or words[-1] != scripts[0]:
        return None
    if words[0] == "torchrun":
        return [sys.executable, "-m", "torch.distributed.run", *words[1:]]
    return [sys.executable, *words[1:]]


def expand(cmd):
    # IPython's `{expr}` in shell lines, evaluated in the notebook's namespace; a
    # brace that doesn't evaluate (an awk program, a shell `${x}`) stays as written.
    def value(match):
        try:
            return str(eval(match.group(1), globals()))
        except Exception:
            return match.group(0)

    return re.sub(r"(?<!\$)\{([^{}]+)\}", value, cmd)


def shell(cmd, _subprocess=subprocess):
    # A failing command doesn't raise, as in IPython: it's reported, and the cell
    # goes on.
    cmd = expand(cmd)
    script = written_script(cmd.strip())
    if script:
        run = dict(args=script)
    elif DATASET_FETCH.fullmatch(cmd.strip()):
        # Into this run's own directory: parallel checks would share /tmp's.
        run = dict(args=cmd.replace("/tmp/ghsparse.sh", "ghsparse.sh"), shell=True)
    else:
        parts = re.split(r"&&|\|\||;|\|", cmd)
        words = {part.split()[0] for part in parts if part.split()}
        if not words <= SAFE_SHELL:
            emit("skipped-shell", cmd)
            return
        run = dict(args=cmd, shell=True)
    code = _subprocess.run(**run, check=False, capture_output=True).returncode
    if code:
        emit("shell-failed", running[0], code, cmd.strip()[:300])


def writefile(name, body):
    with open(name, "w") as f:
        f.write(body)
    written.add(name)


def translate(code):
    # Colab-like handling of shell lines and the common magics.
    lines = code.splitlines()
    if lines and lines[0].startswith("%%"):
        magic, _, arg = lines[0][2:].partition(" ")
        body = "\n".join(lines[1:]) + "\n"
        if magic == "writefile":
            return f"__qa_writefile__({arg.split()[-1]!r}, {body!r})"
        if magic in {"bash", "sh", "script"}:
            return f"__qa_shell__({body!r})"
        lines = lines[1:]
    out = []
    for line in lines:
        indent = line[: len(line) - len(line.lstrip())]
        stripped = line.lstrip()
        if stripped.startswith("!"):
            out.append(f"{indent}__qa_shell__({stripped[1:]!r})")
        elif stripped.startswith("%"):
            magic, _, arg = stripped.lstrip("%").partition(" ")
            keep = magic in {"time", "timeit"} and arg
            out.append(f"{indent}{arg}" if keep else f"{indent}pass")
        else:
            out.append(line)
    return "\n".join(out)


def main():
    builtins.input = no_input
    import getpass
    getpass.getpass = no_input
    if "--smoke" in sys.argv[2:]:
        exec(__SMOKE__, {})
    # Run in the real __main__ so multiprocessing can pickle functions cells define.
    # Cells share it with this runner: its helpers are bound here, so that a cell
    # defining a `translate` or a `json` of its own can't shadow them.
    namespace = sys.modules["__main__"].__dict__
    namespace["__qa_shell__"] = shell
    namespace["__qa_writefile__"] = writefile
    _translate, _emit, _compile, _eval = translate, emit, compile, eval
    _iscoroutine, _run = inspect.iscoroutine, asyncio.run
    _flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
    for i, role, code in json.load(open(sys.argv[1])):
        running[0] = i
        try:
            # Colab allows top-level `await`: such a cell compiles to a coroutine.
            compiled = _compile(_translate(code), f"<cell {i}>", "exec", flags=_flags)
            result = _eval(compiled, namespace)
            if _iscoroutine(result):
                _run(result)
        except BaseException as e:
            _emit(i, role, f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
"""


def runner_source() -> str:
    """The local runner, run as `python runner.py CELLS.json [--smoke]`.

    Returns:
        Python source.
    """
    return RUNNER.replace("__DATASET_FETCH__", repr(DATASET_FETCH.pattern)).replace(
        "__SMOKE__", repr(SMOKE)
    )


def report_lines(stderr: str, returncode: int) -> Iterator[str]:
    """Render a run's captured stderr and exit code as report lines.

    Yields:
        One line per skipped shell command, per kernel death and per shell \
        command that failed (without raising, as in IPython), then the \
        overall execution result, and each cell that raised.
    """
    # Not `splitlines()`: it also splits on `\x1e`, the marker's first character.
    events = [
        json.loads(line.removeprefix(EVENT))
        for line in stderr.split("\n")
        if line.startswith(EVENT)
    ]
    markers = {"skipped-shell", "kernel-died", "shell-failed"}
    # A failure reported again by a rerun (`labs.container`) is reported once.
    failures = list(
        dict.fromkeys(tuple(event) for event in events if event[0] not in markers)
    )
    for _, cmd in (event for event in events if event[0] == "skipped-shell"):
        yield f"  shell command not run (not a data fetch): {cmd[:120]}"
    for _, i, rerun in (event for event in events if event[0] == "kernel-died"):
        yield (
            f"  [{i}] the kernel died: ran the notebook again from the start, as a "
            "trainee would after Colab restarts it"
            if rerun
            else f"  [{i}] the kernel died again"
        )
    shell_failed = dict.fromkeys(
        tuple(event) for event in events if event[0] == "shell-failed"
    )
    for _, i, code, cmd in shell_failed:
        yield f"  [{i}] shell command exited with code {code}: {cmd[:120]}"
    if returncode:
        # Killed (out of memory: -9) or crashed: the cells after the last event
        # never ran.
        yield f"  execution: the runner exited with code {returncode}"
    elif not failures:
        yield "  execution: no code cell raised"
    for i, role, err in failures:
        yield f"  [{i}] {role} cell raised {err}"


def run_notebook(
    notebook: dict[str, Any],
    labels: list[str],
    python: str,
    *,
    smoke: bool,
    timeout: int,
) -> Iterator[str]:
    """Run every code cell of `notebook`.

    Yields:
        The run's report lines (see `report_lines`).
    """
    cells = [
        [i, role, cell_source(cell)]
        for i, (cell, role) in enumerate(zip(notebook["cells"], labels, strict=True))
        if cell.get("cell_type") == "code"
    ]
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "cells.json"
        spec.write_text(json.dumps(cells))
        runner = Path(tmp) / "runner.py"
        runner.write_text(runner_source())
        try:
            proc = subprocess.run(
                [python, str(runner), str(spec), *(["--smoke"] if smoke else [])],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={"MPLBACKEND": "Agg", "PATH": "/usr/bin:/bin", "HOME": tmp},
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            # What ran before the timeout still counts. (`stderr` is bytes here,
            # whatever `text` says.)
            stderr = e.stderr or b""
            yield f"  execution timed out after {timeout}s, cells run until then:"
            yield from report_lines(
                stderr.decode() if isinstance(stderr, bytes) else stderr, 0
            )
            return
    yield from report_lines(proc.stderr, proc.returncode)


def check_notebook(
    path: Path,
    *,
    heading: str = "Solution",
    python: str = sys.executable,
    smoke: bool = False,
    timeout: int = EXEC_TIMEOUT,
    container: "Container | None" = None,
    name: str | None = None,
) -> Iterator[str]:
    """Structural checks plus an execution report for one notebook.

    Structural checks: a `heading` section not collapsed in Colab, an empty
    one, and a stored error output. The execution runs with `python` and
    this module's runner, or, given a `container`, for real in it, as
    `name` (default: the file's name; see `labs.container`).

    Yields:
        One report line per problem or execution result.
    """
    notebook = json.loads(path.read_text(encoding="utf-8"))
    labels = roles(notebook, heading=heading)
    collapsed = set(
        notebook.get("metadata", {}).get("colab", {}).get("collapsed_sections", [])
    )
    for i, (cell, role) in enumerate(zip(notebook["cells"], labels, strict=True)):
        if role == "solution-heading":
            if cell.get("metadata", {}).get("id") not in collapsed:
                yield f"  [{i}] {heading} heading not collapsed in Colab"
            following = notebook["cells"][i + 1] if i + 1 < len(labels) else None
            if following is None or (
                following.get("cell_type") == "markdown"
                and cell_source(following).lstrip().startswith("#")
            ):
                yield f"  [{i}] empty {heading} section"
        for out in cell.get("outputs", []):
            if out.get("output_type") == "error":
                yield f"  [{i}] stored error output: {out.get('ename')}"
    if "solution-heading" not in labels:
        yield f"  no {heading} section at all"
    if container is None:
        yield from run_notebook(notebook, labels, python, smoke=smoke, timeout=timeout)
        return
    from .container import run_in_container

    yield from run_in_container(
        notebook,
        labels,
        name or path.name,
        container,
        smoke=smoke,
        timeout=timeout,
    )


# The `check_notebook` lines that state a fact rather than a problem: a shell line the
# runner without `--container` skips, `nvidia-smi` failing on a CPU, a kernel death a
# rerun recovers from (as Colab's restart would), the verdict of a clean run, and a
# notebook without solutions (a demo).
_FACT_RE = re.compile(
    r"\s*(?:shell command not run|execution: no code cell raised|no .+ section at all$"
    r"|\[\d+\] the kernel died: ran the notebook again"
    r"|\[\d+\] shell command exited with code \d+: nvidia-smi)"
)


def is_problem(line: str) -> bool:
    """Whether a `check_notebook` line reports a problem, which fails the check.

    Returns:
        False for the lines that only state a fact (see `_FACT_RE`).
    """
    return not _FACT_RE.match(line)
