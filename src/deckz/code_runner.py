"""Run a course notes chapter's Python code and compare it with the outputs it shows.

A script, standard library only: `deckz check course-notes-code`
([`course_notes_code`][deckz.course_notes_code]) runs it with the interpreter
`course_notes.code.python` names, which has the libraries the chapters use, not
deckz's. It runs, in a single namespace, in the order the chapter shows them, as
a reader typing them in would:

- each ```` ```pycon ```` session, prompt by prompt, its output compared with
  what the chapter shows under the prompt (as `doctest` does, `...` standing for
  any text);
- each ```` ```python ```` block as a whole, compared with the ```` ```text ````
  block right after it if there is one, else expected to print nothing and not
  to fail;
- a block whose first line names a file (`# bavard.py`, `# integrer.pyx`) is that
  file: it's written to the working directory, for the blocks after it to import
  or read, and runs as a script (in a namespace of its own) only when an output
  block follows it;
- each ```` ```console ```` block, command by command (each after `$ `, its
  output under it), when every program it runs is one `--command` allows: in the
  working directory, with the interpreter's own programs (`python`, `pytest`)
  first on the `PATH`, `uv run <program>` running the program itself. A block
  with any other command (`uv add`, `git push`) isn't run.

A shown error counts by its last line (`ValueError: ...`), the traceback above it
varying with the interpreter. Classes on the block's fence opt out: `{.python
.no-run}` isn't run (a GUI's main loop, a server, `input()`, a deliberately
incomplete fragment), `{.pycon .output-varies}` runs without its output compared
(timings, addresses, the machine's own state). Once a block fails, the
`NameError`s after it are counted, not reported one by one: they're most likely
the names it failed to define.

The setup chapters (`--setup`) run first, the same way, their own outputs
unchecked: the example data another chapter builds. Each output (stdout and
stderr, the chapter's own and its subprocesses') is captured at the file
descriptor level, as a terminal shows it.

Usage: `python code_runner.py RESULT [--timeout S] [--setup CHAPTER]...
[--command PROGRAM]... CHAPTER`.
RESULT receives one JSON object: `examples` (how many ran), `problems` (each
with `line`, `source`, `expected`, `got`, `error`, the last line of the error
it raised if any, `console`, whether it's a console command, and `setup`, the
setup chapter it comes from if any) and
`cascaded` (the `NameError`s counted after a failure). Before each example,
`RESULT.at` receives `path:line`, so that a chapter killed by its overall time
limit tells where it was.
"""

import argparse
import doctest
import io
import json
import os
import re
import runpy
import shlex
import signal
import subprocess
import sys
import tempfile
import traceback
import warnings
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

NO_RUN = "no-run"
"""Fence class of a block not to run."""
OUTPUT_VARIES = "output-varies"
"""Fence class of a block run without its output compared."""
_OUTPUT_LANGS = frozenset({"text", "output"})
_FLAGS = doctest.ELLIPSIS
_FENCE = re.compile(r"^(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^\n]*)\n", re.MULTILINE)
_FILE_HEADER = re.compile(r"#\s*(?P<name>[\w.-]+(?:/[\w.-]+)*\.\w+)\s*")
_PROMPT = "$ "
_UV_RUN = re.compile(r"(^|[|&;(]\s*)((?:\w+=\S*\s+)*)uv run (?=[^-\s])")
_CHAINING = frozenset({"|", "||", "&&", ";", "&", "(", ")"})
_REDIRECTION = frozenset({">", ">>", "<", ">&", "<&", "&>"})
_ASSIGNMENT = re.compile(r"\w+=\S*")
_status = 0
"""The exit status of the last command run, for an `echo $?` after it."""


@dataclass(frozen=True)
class Block:
    line: int
    """1-based line of its opening fence."""
    classes: tuple[str, ...]
    """Its language first (`pycon`, `python`), then its other classes."""
    body: str
    output: str | None
    """The ```` ```text ```` block right after it, if any."""

    @property
    def lang(self) -> str:
        return self.classes[0] if self.classes else ""

    @property
    def file_name(self) -> str | None:
        # The file a block is, from a first line like `# bavard.py`.
        first = self.body.split("\n", 1)[0]
        match = _FILE_HEADER.fullmatch(first)
        if match is None or ".." in match["name"].split("/"):
            return None
        return match["name"]


@dataclass(frozen=True)
class Example:
    line: int
    source: str
    expected: str | None
    """What it should print; None when its output isn't compared."""
    mode: str
    """`single` (a prompt), `exec` (a block), `script` (a file block run), \
    `file` (a file block written) or `shell` (a console command)."""
    file_name: str | None = None
    """The file a block is written to, if it's one."""
    status_shown: bool = False
    """A console command followed by `echo $?`, which shows how it exited."""


def blocks(text: str) -> list[Block]:
    """Every fenced code block of `text`, in order.

    Returns:
        Each block, with the output block that follows it, if any.
    """
    found: list[tuple[int, tuple[str, ...], str, int, int]] = []
    pos = 0
    while (start := _FENCE.search(text, pos)) is not None:
        fence = start["fence"]
        close = re.compile(
            rf"^{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$", re.MULTILINE
        )
        end = close.search(text, start.end())
        if end is None:
            break
        info = start["info"].strip()
        classes = (
            tuple(re.findall(r"\.([\w-]+)", info))
            if info.startswith("{")
            else tuple(info.split()[:1])
        )
        line = text.count("\n", 0, start.start()) + 1
        found.append(
            (line, classes, text[start.end() : end.start()], start.start(), end.end())
        )
        pos = end.end()
    result = []
    for index, (line, classes, body, _, end) in enumerate(found):
        output = None
        if index + 1 < len(found):
            _, next_classes, next_body, next_start, _ = found[index + 1]
            if (
                next_classes[:1]
                and next_classes[0] in _OUTPUT_LANGS
                and not text[end:next_start].strip()
            ):
                output = next_body
        result.append(Block(line, classes, body, output))
    return result


def _without_uv_run(command: str) -> str:
    # `uv run ruff check` runs `ruff check`: the environment is already there.
    return _UV_RUN.sub(r"\1\2", command)


def programs(command: str) -> list[str] | None:
    """The programs a console command runs.

    Returns:
        The first word of each command it chains (`|`, `&&`, `;`), past \
        variable assignments and `uv run`; None if it runs others it can't \
        name (`$(...)`, backquotes) or doesn't parse.
    """
    command = _without_uv_run(command.replace("\\\n", " "))
    if "$(" in command or "`" in command:
        return None
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    found = []
    starts, skip = True, False
    for token in tokens:
        if skip:
            skip = False
        elif token in _CHAINING:
            starts = True
        elif token in _REDIRECTION:
            skip = True
        elif starts and not _ASSIGNMENT.fullmatch(token):
            found.append(token)
            starts = False
    return found


def _commands(block: Block) -> list[tuple[int, str, str]]:
    # Each command of a console block: its line, the command (continued past
    # a final `\`, the shell's `> ` prompt left out), what it prints.
    found: list[tuple[int, list[str], list[str]]] = []
    for index, line in enumerate(block.body.splitlines()):
        if found and not found[-1][2] and found[-1][1][-1].endswith("\\"):
            found[-1][1].append(line.removeprefix("> "))
        elif line.startswith(_PROMPT) or line.rstrip() == _PROMPT.strip():
            found.append((block.line + 1 + index, [line[len(_PROMPT) :]], []))
        elif found:
            found[-1][2].append(line)
    return [
        (line, "\n".join(command), "\n".join(output)) for line, command, output in found
    ]


def examples(text: str, commands: frozenset[str] = frozenset()) -> Iterator[Example]:
    """The examples of `text` to run, in order.

    Args:
        text: A chapter.
        commands: The programs a console block may run.

    Yields:
        Each prompt of a `pycon` block, each `python` block, each file block, \
        each command of a console block running `commands` only.
    """
    parser = doctest.DocTestParser()
    for block in blocks(text):
        if NO_RUN in block.classes:
            continue
        compared = OUTPUT_VARIES not in block.classes
        if block.lang == "pycon":
            for example in parser.get_examples(block.body):
                expected = example.want if example.exc_msg is None else example.exc_msg
                yield Example(
                    block.line + 1 + example.lineno,
                    example.source,
                    expected if compared else None,
                    "single",
                )
        elif (file_name := block.file_name) is not None:
            yield Example(
                block.line,
                block.body,
                (block.output if compared else None)
                if block.output is not None
                else "",
                "script" if block.output is not None else "file",
                file_name,
            )
        elif block.lang == "python":
            yield Example(
                block.line,
                block.body,
                (block.output or "") if compared else None,
                "exec",
            )
        elif block.lang == "console":
            found = _commands(block)
            ran = [programs(command) for _, command, _ in found]
            if found and all(
                names is not None and set(names) <= commands for names in ran
            ):
                after = [command for _, command, _ in found[1:]] + [""]
                for (line, command, output), following in zip(
                    found, after, strict=True
                ):
                    yield Example(
                        line,
                        command,
                        output if compared else None,
                        "shell",
                        status_shown=following.startswith("echo $?"),
                    )


class _TimeoutError(Exception):
    pass


def _alarm(signum: int, frame: FrameType | None) -> None:
    raise _TimeoutError


def _shell(example: Example, timeout: int) -> tuple[str, str | None]:
    # Run a console command in `bash`, `$?` the previous command's status.
    global _status
    try:
        done = subprocess.run(
            ["bash", "-c", f"(exit {_status}); {_without_uv_run(example.source)}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        _status = 124
        got = (expired.stdout or b"").decode("utf-8", errors="replace")
        return got, f"TimeoutError: still running after {timeout} s, stopped"
    _status = done.returncode
    return done.stdout.decode("utf-8", errors="replace"), None


def _run(
    example: Example, namespace: dict[str, object], timeout: int
) -> tuple[str, str | None]:
    # Run `example`; return what it printed and the last line of its error.
    if example.mode == "shell":
        return _shell(example, timeout)
    if example.mode == "file":
        assert example.file_name is not None
        path = Path(example.file_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(example.source, encoding="utf-8")
        return "", None
    with tempfile.TemporaryFile() as capture:
        sys.stdout.flush()
        sys.stderr.flush()
        saved = os.dup(1), os.dup(2)
        os.dup2(capture.fileno(), 1)
        os.dup2(capture.fileno(), 2)
        stream = io.TextIOWrapper(
            io.FileIO(1, "w", closefd=False), encoding="utf-8", write_through=True
        )
        old = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = stream
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(timeout)
        error = None
        try:
            if example.mode == "script":
                assert example.file_name is not None
                Path(example.file_name).write_text(example.source, encoding="utf-8")
                sys.argv = [example.file_name]
                runpy.run_path(example.file_name, run_name="__main__")
            else:
                exec(compile(example.source, "<stdin>", example.mode), namespace)
        except _TimeoutError:
            error = f"TimeoutError: still running after {timeout} s, stopped"
        except SystemExit as exit_:
            if exit_.code not in (None, 0):
                error = f"SystemExit: {exit_.code}"
        except BaseException as exception:
            error = traceback.format_exception_only(exception)[-1].strip()
        finally:
            signal.alarm(0)
            sys.argv = [""]
            stream.flush()
            sys.stdout, sys.stderr = old
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])
        capture.seek(0)
        return capture.read().decode("utf-8", errors="replace"), error


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def matches(expected: str, got: str, error: str | None) -> bool:
    """Whether what ran (`got`, `error`) is what the chapter shows (`expected`).

    Returns:
        True if the output matches, `...` standing for any text; for an error, \
        if the last line shown is the error's.
    """
    checker = doctest.OutputChecker()
    if error is None:
        return checker.check_output(_normalized(expected), _normalized(got), _FLAGS)
    shown = _last_line(expected)
    return bool(shown) and checker.check_output(shown + "\n", error + "\n", _FLAGS)


def _normalized(text: str) -> str:
    # Without trailing spaces, which a Markdown file doesn't keep (pandas pads
    # its index's header line), and with one final newline.
    lines = [line.rstrip() for line in text.rstrip().splitlines()]
    return "\n".join(lines) + "\n" if lines else ""


def run_chapter(
    path: Path,
    namespace: dict[str, object],
    timeout: int,
    progress: Path,
    *,
    checked: bool = True,
    commands: frozenset[str] = frozenset(),
) -> tuple[int, list[dict[str, object]], int]:
    """Run `path`'s examples in `namespace`, its console blocks running `commands`.

    Returns:
        How many examples ran, the problems (all of them if `checked`, its \
        errors only otherwise), and the `NameError`s counted after a failure.
    """
    text = path.read_text(encoding="utf-8")
    count = 0
    problems: list[dict[str, object]] = []
    cascaded = 0
    failed = False
    for example in examples(text, commands):
        count += 1
        progress.write_text(f"{path}:{example.line}", encoding="utf-8")
        got, error = _run(example, namespace, timeout)
        if example.expected is None or not checked:
            good = error is None
        else:
            good = matches(example.expected, got, error)
        if (
            good
            and example.mode == "shell"
            and _status
            and checked
            and not example.status_shown
            and not (example.expected or "").strip()
        ):
            # A command failing silently: its error isn't shown.
            good, error = False, f"exit status {_status}"
        if good:
            continue
        if failed and error is not None and error.startswith("NameError"):
            cascaded += 1
            continue
        failed = failed or error is not None
        problems.append(
            {
                "line": example.line,
                "source": example.source.rstrip("\n"),
                "expected": example.expected or "",
                "got": got + (error + "\n" if error else ""),
                "error": error,
                "console": example.mode == "shell",
            }
        )
    return count, problems, cascaded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("result", type=Path)
    parser.add_argument("chapter", type=Path)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--setup", type=Path, action="append", default=[])
    parser.add_argument("--command", action="append", default=[])
    args = parser.parse_args()
    commands = frozenset(args.command)
    # Like an interactive session: the working directory first on the path
    # (for the file blocks), not this script's own directory, and no
    # arguments. Figures draw nowhere, without `show()` warning about it.
    sys.path[0] = ""
    sys.argv = [""]
    # The console blocks' `python`, `pytest`, `ruff` are the interpreter's.
    os.environ.setdefault("MPLBACKEND", "Agg")
    bin_dir = str(Path(sys.executable).parent)
    os.environ["PATH"] = os.pathsep.join([bin_dir, os.environ.get("PATH", "")])
    warnings.filterwarnings("ignore", "FigureCanvasAgg is non-interactive")
    progress = args.result.with_name(args.result.name + ".at")
    namespace: dict[str, object] = {
        "__name__": "__main__",
        "__builtins__": __builtins__,
    }
    problems: list[dict[str, object]] = []
    for setup in args.setup:
        _, setup_problems, _ = run_chapter(
            setup, namespace, args.timeout, progress, checked=False, commands=commands
        )
        problems.extend({**problem, "setup": str(setup)} for problem in setup_problems)
    count, chapter_problems, cascaded = run_chapter(
        args.chapter, namespace, args.timeout, progress, commands=commands
    )
    problems.extend(chapter_problems)
    args.result.write_text(
        json.dumps({"examples": count, "problems": problems, "cascaded": cascaded}),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
