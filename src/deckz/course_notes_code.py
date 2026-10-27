"""Run the course notes chapters' Python code, and compare it with what they show.

What `deckz check course-notes-code` does. Each chapter runs in a process of its
own, through [`code_runner`][deckz.code_runner], with the interpreter
`course_notes.code.python` names (deckz's own when unset), in a scratch working
directory: its code runs as a reader would type it in, and each output it shows
is compared with what the code prints. `course_notes.code.setup` names what a
chapter's examples need first: other chapters (the example data they build) and
data files, linked into the working directory.
"""

import json
import os
import signal
import subprocess
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

from . import code_runner

if TYPE_CHECKING:
    from .configuring.settings import GlobalSettings

_SHOWN_LINES = 30
_STARTUP_LIMIT = 1800
"""Seconds the interpreter may take to start (its environment installed)."""


def _rel(path: Path, git_dir: Path) -> str:
    return (
        path.relative_to(git_dir).as_posix()
        if path.is_relative_to(git_dir)
        else str(path)
    )


def _content_path(settings: "GlobalSettings", chapter: Path) -> PurePosixPath:
    # The chapter's path, relative to the course notes directory, without
    # extension nor `en/`: what `course_notes.code.setup`'s patterns match.
    rel = PurePosixPath(chapter.relative_to(settings.paths.course_notes_dir).as_posix())
    parent = rel.parent.parent if rel.parent.name == "en" else rel.parent
    return parent / rel.stem


def _setup(settings: "GlobalSettings", chapter: Path) -> tuple[list[Path], list[Path]]:
    # The chapters to run first and the files to link, for `chapter`.
    git_dir = settings.paths.git_dir
    path = _content_path(settings, chapter)
    english = chapter.parent.name == "en"
    chapters: list[Path] = []
    files: list[Path] = []
    for pattern, entries in settings.course_notes.code.setup.items():
        if not path.full_match(pattern):
            continue
        for entry in entries:
            target = git_dir / entry
            if target.suffix in settings.file_extensions:
                translated = target.parent / "en" / target.name
                if english and translated.is_file():
                    target = translated
                if target.resolve() != chapter.resolve() and target not in chapters:
                    chapters.append(target)
            elif target not in files:
                files.append(target)
    return chapters, files


def _command(settings: "GlobalSettings") -> list[str]:
    import sys

    python = settings.course_notes.code.python or (sys.executable,)
    git_dir = str(settings.paths.git_dir)
    return [part.replace("{git_dir}", git_dir) for part in python]


def _indented(text: str) -> str:
    lines = text.rstrip("\n").splitlines() or [""]
    if len(lines) > _SHOWN_LINES:
        lines = [*lines[:_SHOWN_LINES], f"[{len(lines) - _SHOWN_LINES} more lines]"]
    return "\n".join(f"      | {line}" for line in lines)


def _message(where: str, problem: dict[str, Any], chapter: str) -> str:
    # What went wrong with one example, and its fix, then what it printed.
    got = _indented(problem["got"])
    if "setup" in problem:
        return (
            f"{where}: fails when it runs as the setup of {chapter} "
            f"(course_notes.code.setup)\n{got}"
        )
    if (problem["error"] or "").startswith("TimeoutError: still running"):
        return (
            f"{where}: {problem['error'].removeprefix('TimeoutError: ')}: mark the "
            "block `.no-run` if it waits (a GUI's main loop, a server, `input()`), "
            "or make it shorter\n"
            f"{got}"
        )
    if problem["error"] is not None:
        return (
            f"{where}: raises {problem['error']}: fix the code, show the error in "
            "an output block after it, or mark the block `.no-run` if it isn't "
            f"meant to run (`{{.python .no-run}}`)\n{got}"
        )
    if not problem["expected"].strip():
        return (
            f"{where}: prints what the chapter doesn't show: add it in a ```text "
            "block right after (and mark the block `.output-varies` if it changes "
            f"from one run to the next)\n{got}"
        )
    return (
        f"{where}: the output shown isn't what it prints, which is this (mark "
        f"the block `.output-varies` if it changes from one run to the next)\n{got}"
    )


def _run(settings: "GlobalSettings", chapter: Path) -> list[str]:
    git_dir = settings.paths.git_dir
    rel = _rel(chapter, git_dir)
    text = chapter.read_text(encoding="utf-8")
    count = sum(1 for _ in code_runner.examples(text))
    if not count:
        return []
    code = settings.course_notes.code
    setup_chapters, setup_files = _setup(settings, chapter)
    if missing := [
        path for path in (*setup_chapters, *setup_files) if not path.exists()
    ]:
        return [
            f"{rel}: course_notes.code.setup names {_rel(path, git_dir)}, which "
            "doesn't exist: fix the path in deckz.yml"
            for path in missing
        ]
    with TemporaryDirectory(prefix="deckz-code-") as scratch:
        work = Path(scratch) / "work"
        work.mkdir()
        for file in setup_files:
            (work / file.name).symlink_to(file.resolve())
        result = Path(scratch) / "result.json"
        progress = result.with_name(result.name + ".at")
        command = [
            *_command(settings),
            str(Path(code_runner.__file__).resolve()),
            str(result),
            str(chapter.resolve()),
            "--timeout",
            str(code.timeout),
        ]
        for setup in setup_chapters:
            command += ["--setup", str(setup.resolve())]
        env = {
            **os.environ,
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "NO_COLOR": "1",
        }
        try:
            process = subprocess.Popen(
                command,
                cwd=work,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as error:
            return [
                f"{rel}: can't run {command[0]} ({error}): set "
                "course_notes.code.python in deckz.yml to a command running Python"
            ]
        timed_out = _wait(process, progress, code.timeout * (count + 1))
        _, stderr = process.communicate()
        if timed_out:
            where = progress.read_text(encoding="utf-8") if progress.is_file() else rel
            return [
                f"{_relative_where(where, git_dir)}: still running after "
                f"{code.timeout * (count + 1)} s, stopped: mark the block that "
                "waits (a GUI's main loop, a server, `input()`) `.no-run`"
            ]
        if not result.is_file():
            tail = stderr.decode("utf-8", errors="replace").strip().splitlines()[-5:]
            return [
                f"{rel}: the code runner failed (exit code {process.returncode}), "
                "check course_notes.code.python in deckz.yml:\n"
                + _indented("\n".join(tail))
            ]
        report = json.loads(result.read_text(encoding="utf-8"))
    problems = []
    for problem in report["problems"]:
        source = Path(problem.get("setup", chapter))
        where = f"{_rel(source, git_dir)}:{problem['line']}"
        problems.append(_message(where, problem, rel))
    if report["cascaded"]:
        problems.append(
            f"{rel}: {report['cascaded']} more example(s) raise NameError, most "
            "likely on names the failure above left undefined: fix it first"
        )
    return problems


def _relative_where(where: str, git_dir: Path) -> str:
    path, _, line = where.rpartition(":")
    return f"{_rel(Path(path), git_dir)}:{line}" if path else where


def _wait(process: subprocess.Popen[bytes], progress: Path, limit: int) -> bool:
    # Wait for `process`; kill its session and return True once it has run
    # its examples for more than `limit` seconds (from its first one).
    started = time.monotonic()
    first: float | None = None
    while process.poll() is None:
        now = time.monotonic()
        if first is None and progress.is_file():
            first = now
        if (
            first is not None and now - first > limit
        ) or now - started > _STARTUP_LIMIT + limit:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            return True
        time.sleep(0.2)
    return False


def check_chapters(settings: "GlobalSettings", chapters: Iterable[Path]) -> list[str]:
    """Run each of `chapters`' code and compare it with what it shows.

    Args:
        settings: The repository's settings (`course_notes.code`).
        chapters: The chapters to run (absolute paths).

    Returns:
        Every problem, chapter by chapter, each starting with `path:line`.
    """
    found: Sequence[Path] = sorted(chapters)
    with ThreadPoolExecutor(
        max_workers=max(1, settings.course_notes.code.jobs)
    ) as pool:
        results = list(pool.map(lambda chapter: _run(settings, chapter), found))
    return [problem for problems in results for problem in problems]
