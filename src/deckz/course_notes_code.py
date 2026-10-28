"""Run the course notes chapters' Python code, and compare it with what they show.

What `deckz check course-notes-code` does. Each chapter runs in a process of its
own, through [`code_runner`][deckz.code_runner], with the interpreter
`course_notes.code.python` names (deckz's own when unset), in a scratch working
directory: its code runs as a reader would type it in, and each output it shows
is compared with what the code prints. `course_notes.code.setup` names what a
chapter's examples need first: other chapters (the example data they build) and
data files, linked into the working directory; `course_notes.code.requirements`
the packages it needs beyond the interpreter's.

The data sets a chapter links to (`course_notes.code.datasets`) come from that
repository's local clone, under the name a download gives them: copied, or
linked when they're big (and then checked unchanged after the run). The clone
must have them committed and pushed, or the reader's link leads nowhere.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from os.path import relpath
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

from . import code_runner

if TYPE_CHECKING:
    from .configuring.settings import DatasetsSettings, GlobalSettings

_SHOWN_LINES = 30
_STARTUP_LIMIT = 1800
"""Seconds the interpreter may take to start (its environment installed)."""
_LINKED_SIZE = 50 * 2**20
"""Data files bigger than this are linked into the working directory, not copied."""
_SPARSE_CLONE = re.compile(r"bash \S*ghsparse\.sh (?P<path>[\w.-]+)")


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


def _matching(table: dict[str, tuple[str, ...]], path: PurePosixPath) -> list[str]:
    # The entries of `table`'s patterns `path` matches, in order.
    return [
        entry
        for pattern, entries in table.items()
        if path.full_match(pattern)
        for entry in entries
    ]


def unmatched_patterns(
    settings: "GlobalSettings", chapters: Iterable[Path]
) -> list[str]:
    """The patterns of `course_notes.code.setup` and `requirements` matching no chapter.

    Args:
        settings: The repository's settings.
        chapters: Every chapter.

    Returns:
        One problem per pattern (most likely a section moved or renamed).
    """
    paths = [_content_path(settings, chapter) for chapter in chapters]
    code = settings.course_notes.code
    return [
        f"deckz.yml: course_notes.code.{name}'s pattern {pattern} matches no "
        "chapter: fix it, or remove it"
        for name, table in (("setup", code.setup), ("requirements", code.requirements))
        for pattern in table
        if not any(path.full_match(pattern) for path in paths)
    ]


def _setup(settings: "GlobalSettings", chapter: Path) -> tuple[list[Path], list[Path]]:
    # The chapters to run first and the files to link, for `chapter`.
    git_dir = settings.paths.git_dir
    english = chapter.parent.name == "en"
    chapters: list[Path] = []
    files: list[Path] = []
    path = _content_path(settings, chapter)
    for entry in _matching(settings.course_notes.code.setup, path):
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


def _command(settings: "GlobalSettings", chapter: Path) -> list[str] | None:
    # The interpreter's command for `chapter`, its requirements in place of
    # `{with}`; None if it has requirements and no `{with}`.
    import sys

    python = settings.course_notes.code.python or (sys.executable,)
    git_dir = str(settings.paths.git_dir)
    packages = _matching(
        settings.course_notes.code.requirements, _content_path(settings, chapter)
    )
    if packages and "{with}" not in python:
        return None
    command = []
    for part in python:
        if part == "{with}":
            command += [arg for package in packages for arg in ("--with", package)]
        else:
            command.append(part.replace("{git_dir}", git_dir))
    return command


def _clone(settings: "GlobalSettings", datasets: "DatasetsSettings") -> Path:
    return Path(datasets.path.replace("{git_dir}", str(settings.paths.git_dir)))


def _shown(path: Path, git_dir: Path) -> str:
    # `../datasets` for the usual sibling clone, the full path for any other.
    shown = relpath(path, git_dir)
    return str(path) if shown.count("..") > 1 else shown


def dataset_links(url: str, text: str) -> list[str]:
    """The paths in the data sets repository at `url` that `text` links to.

    Returns:
        Each path once, in order: from its file links (`<url>/raw/...`, \
        `<url>/blob/...`), its directory links (`<url>/tree/...`), and its \
        sparse clones (`bash /tmp/ghsparse.sh <directory>`).
    """
    links = re.compile(
        rf"{re.escape(url.rstrip('/'))}/(?:raw|blob|tree)/(?:refs/heads/)?[\w.-]+/"
        r"(?P<path>[^\s)\"'`<>\]]+)"
    )
    found = [match["path"].rstrip(".,;:") for match in links.finditer(text)]
    if "ghsparse.sh" in found:
        found += [match["path"] for match in _SPARSE_CLONE.finditer(text)]
    return list(dict.fromkeys(path for path in found if path != "ghsparse.sh"))


def _git(clone: Path, *args: str) -> str | None:
    done = subprocess.run(
        ["git", "-C", str(clone), *args], capture_output=True, text=True, check=False
    )
    return None if done.returncode else done.stdout.strip()


def _published(clone: Path, path: str, shown: str) -> str | None:
    # What keeps `path` of `clone` from the reader's link, if anything.
    if _git(clone, "rev-parse", "--git-dir") is None:
        return None
    if _git(clone, "status", "--porcelain", "--", path):
        return (
            f"isn't committed in {shown}: commit it and push it, the chapter's "
            "link leads nowhere until then"
        )
    if _git(clone, "rev-parse", "@{upstream}") is None:
        return None
    if _git(clone, "log", "--format=%h", "@{upstream}..HEAD", "--", path):
        return (
            f"isn't pushed from {shown}: `git -C {shown} push`, the chapter's "
            "link leads nowhere until then"
        )
    return None


def _datasets(
    settings: "GlobalSettings", texts: Iterable[str], rel: str
) -> tuple[list[tuple[Path, str]], list[str]]:
    # The data set files and directories the chapter (and its setup chapters)
    # link to, each with the name it takes in the working directory, and
    # what's wrong with them.
    datasets = settings.course_notes.code.datasets
    if datasets is None:
        return [], []
    paths = list(
        dict.fromkeys(
            path for text in texts for path in dataset_links(datasets.url, text)
        )
    )
    if not paths:
        return [], []
    clone = _clone(settings, datasets)
    shown = _shown(clone, settings.paths.git_dir)
    if not clone.is_dir():
        return [], [
            f"{rel}: links to {datasets.url}, whose clone {shown} doesn't exist: "
            f"`git clone {datasets.url} {shown}`, or set "
            "course_notes.code.datasets.path in deckz.yml"
        ]
    problems = []
    sources: list[tuple[Path, str]] = []
    names: dict[str, str] = {}
    for path in paths:
        source = clone / path
        if not source.exists():
            problems.append(
                f"{rel}: links to {path}, which isn't in {shown}: pull it (`git -C "
                f"{shown} pull`), or add it there and push it"
            )
            continue
        if (why := _published(clone, path, shown)) is not None:
            problems.append(f"{rel}: links to {path}, which {why}")
        name = PurePosixPath(path).name
        if name in names:
            problems.append(
                f"{rel}: links to {names[name]} and {path}, both downloaded as "
                f"{name}: link their directories instead, and read them there"
            )
            continue
        names[name] = path
        sources.append((source, name))
    return sources, problems


def _place(
    sources: Iterable[tuple[Path, str]], work: Path
) -> dict[Path, tuple[int, int]]:
    # Copy the data sets into `work`, linking the big files: returns each
    # linked file's modification time and size.
    linked: dict[Path, tuple[int, int]] = {}

    def copy(source: str, target: str) -> None:
        stat = Path(source).stat()
        if stat.st_size > _LINKED_SIZE:
            Path(target).symlink_to(Path(source).resolve())
            linked[Path(source)] = (stat.st_mtime_ns, stat.st_size)
        else:
            shutil.copy2(source, target)

    for source, name in sources:
        if source.is_dir():
            shutil.copytree(source, work / name, copy_function=copy)
        else:
            copy(str(source), str(work / name))
    return linked


def _overwritten(
    linked: dict[Path, tuple[int, int]], settings: "GlobalSettings", rel: str
) -> list[str]:
    # The linked data set files the chapter's code changed.
    datasets = settings.course_notes.code.datasets
    if datasets is None:
        return []
    clone = _clone(settings, datasets)
    shown = _shown(clone, settings.paths.git_dir)
    problems = []
    for path, (mtime, size) in linked.items():
        stat = path.stat()
        if (stat.st_mtime_ns, stat.st_size) != (mtime, size):
            inside = path.relative_to(clone).as_posix()
            problems.append(
                f"{rel}: writes over {inside}, linked from {shown} (rather than "
                "copied, being big): write to another file, and restore it "
                f"(`git -C {shown} restore {inside}`)"
            )
    return problems


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
    if (problem["error"] or "").startswith("exit status"):
        return (
            f"{where}: fails ({problem['error']}) and the chapter shows nothing: "
            f"fix the command, or show what it prints under it\n{got}"
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
        place = (
            "under the command"
            if problem.get("console")
            else "in a ```text block right after"
        )
        return (
            f"{where}: prints what the chapter doesn't show: add it {place} (and "
            "mark the block `.output-varies` if it changes from one run to the "
            f"next)\n{got}"
        )
    return (
        f"{where}: the output shown isn't what it prints, which is this (mark "
        f"the block `.output-varies` if it changes from one run to the next)\n{got}"
    )


def _run(settings: "GlobalSettings", chapter: Path) -> list[str]:
    git_dir = settings.paths.git_dir
    rel = _rel(chapter, git_dir)
    text = chapter.read_text(encoding="utf-8")
    code = settings.course_notes.code
    commands = frozenset(code.commands)
    count = sum(1 for _ in code_runner.examples(text, commands))
    if not count:
        return []
    setup_chapters, setup_files = _setup(settings, chapter)
    if missing := [
        path for path in (*setup_chapters, *setup_files) if not path.exists()
    ]:
        return [
            f"{rel}: course_notes.code.setup names {_rel(path, git_dir)}, which "
            "doesn't exist: fix the path in deckz.yml"
            for path in missing
        ]
    interpreter = _command(settings, chapter)
    if interpreter is None:
        return [
            f"{rel}: course_notes.code.requirements names packages for it, and "
            'course_notes.code.python has no "{with}" to pass them: add it'
        ]
    texts = [text, *(path.read_text(encoding="utf-8") for path in setup_chapters)]
    data, problems = _datasets(settings, texts, rel)
    if any("doesn't exist" in problem for problem in problems):
        return problems
    with TemporaryDirectory(prefix="deckz-code-") as scratch:
        work = Path(scratch) / "work"
        work.mkdir()
        for file in setup_files:
            (work / file.name).symlink_to(file.resolve())
        linked = _place(data, work)
        result = Path(scratch) / "result.json"
        command = [
            *interpreter,
            str(Path(code_runner.__file__).resolve()),
            str(result),
            str(chapter.resolve()),
            "--timeout",
            str(code.timeout),
        ]
        for setup in setup_chapters:
            command += ["--setup", str(setup.resolve())]
        for program in code.commands:
            command += ["--command", program]
        problems += _execute(settings, chapter, command, result, count)
        problems += _overwritten(linked, settings, rel)
    return problems


def _execute(
    settings: "GlobalSettings",
    chapter: Path,
    command: list[str],
    result: Path,
    count: int,
) -> list[str]:
    # Run `command`, the code runner on `chapter` (`count` examples), in the
    # `work` directory next to `result`: what it found.
    git_dir = settings.paths.git_dir
    rel = _rel(chapter, git_dir)
    timeout = settings.course_notes.code.timeout
    progress = result.with_name(result.name + ".at")
    # Qt draws nowhere: a GUI chapter's widgets build without a display. The
    # programs speak English, as on Colab, whatever the machine's language.
    env = {
        **os.environ,
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NO_COLOR": "1",
        "QT_QPA_PLATFORM": "offscreen",
        "LC_ALL": "C.UTF-8",
    }
    try:
        process = subprocess.Popen(
            command,
            cwd=result.parent / "work",
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
    timed_out = _wait(process, progress, timeout * (count + 1))
    _, stderr = process.communicate()
    if timed_out:
        where = progress.read_text(encoding="utf-8") if progress.is_file() else rel
        return [
            f"{_relative_where(where, git_dir)}: still running after "
            f"{timeout * (count + 1)} s, stopped: mark the block that "
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
