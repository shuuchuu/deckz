"""Execute every code cell of a notebook in order, in a throwaway directory.

Mirrors Colab's handling of shell lines (`!cmd`) and the common magics
(`%%writefile`, `%%bash`, `%time`), reporting which cells raise, in order.
Never runs a lab's own git/pip/publish commands: only a small allow-list of
harmless data-fetch shell commands run, plus the repo's standard dataset
fetch script, plus a script the notebook itself wrote with `%%writefile`.
"""

import json
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .inspecting import roles
from .notebook import cell_source

EXEC_TIMEOUT = 300

# Events go to stderr behind this marker: a library may print lines of its own there
# (Lightning's `[rank: 0] Seed set to 0`, Optuna's `[I 2026-...] Trial ...`).
EVENT = "\x1eQA "

RUNNER = r"""
import ast, asyncio, builtins, inspect, json, re, shlex, subprocess, sys

EVENT = "\x1eQA "
# Shell lines (`!cmd`, `%%bash`) run only if every command is a harmless data fetch:
# a lab may `uv publish`, `pip install` or `git push`, which a QA run must never do.
SAFE_SHELL = {
    "wget", "curl", "unzip", "tar", "gunzip", "ls",
    "cat", "head", "mkdir", "cp", "mv", "echo",
}
# The repo's standard dataset fetch (see labs/README.md), exactly: `bash` runs
# nothing else.
DATASET_FETCH = re.compile(
    r"wget -qO- https://github\.com/shuuchuu/datasets/raw/refs/heads/main/ghsparse\.sh"
    r" \| bash -s [\w.-]+"
)
# Scripts the notebook itself wrote with `%%writefile`, which `python` and
# `torchrun` may run.
written = set()


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
    cmd = expand(cmd)
    script = written_script(cmd.strip())
    if script:
        _subprocess.run(script, check=True, capture_output=True)
        return
    if DATASET_FETCH.fullmatch(cmd.strip()):
        _subprocess.run(cmd, shell=True, check=True, capture_output=True)
        return
    words = {part.split()[0] for part in re.split(r"&&|\|\||;|\|", cmd) if part.split()}
    if not words <= SAFE_SHELL:
        emit("skipped-shell", cmd)
        return
    _subprocess.run(cmd, shell=True, check=True, capture_output=True)


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


def smoke():
    # Every Lightning Trainer capped to one short epoch.
    caps = {"max_epochs": 1, "limit_train_batches": 3, "limit_val_batches": 2}
    for name in ("lightning", "pytorch_lightning"):
        try:
            trainer = __import__(name).Trainer
        except ImportError:
            continue
        init = trainer.__init__

        def capped(self, *args, _init=init, **kwargs):
            kwargs.pop("max_steps", None)
            _init(self, *args, **{**kwargs, **caps})

        trainer.__init__ = capped


def main():
    builtins.input = no_input
    import getpass
    getpass.getpass = no_input
    if "--smoke" in sys.argv[2:]:
        smoke()
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
        try:
            # Colab allows top-level `await`: such a cell compiles to a coroutine.
            compiled = _compile(_translate(code), f"<cell {i}>", "exec", flags=_flags)
            result = _eval(compiled, namespace)
            if _iscoroutine(result):
                _run(result)
        except BaseException as e:
            _emit(i, role, f"{type(e).__name__}: {e}")


main()
"""


def report_lines(stderr: str, returncode: int) -> Iterator[str]:
    """Render a run's captured stderr and exit code as report lines.

    Yields:
        One line per skipped shell command, the overall execution result, \
        and each cell that raised.
    """
    # Not `splitlines()`: it also splits on `\x1e`, the marker's first character.
    events = [
        json.loads(line.removeprefix(EVENT))
        for line in stderr.split("\n")
        if line.startswith(EVENT)
    ]
    failures = [event for event in events if event[0] != "skipped-shell"]
    for _, cmd in (event for event in events if event[0] == "skipped-shell"):
        yield f"  shell command not run (not a data fetch): {cmd[:120]}"
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
        runner.write_text(RUNNER)
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
) -> Iterator[str]:
    """Structural checks plus an execution report for one notebook.

    Structural checks: a `heading` section not collapsed in Colab, an empty
    one, and a stored error output.

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
    yield from run_notebook(notebook, labels, python, smoke=smoke, timeout=timeout)
