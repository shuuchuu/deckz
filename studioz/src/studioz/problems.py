"""The Problems panel: what a workspace has left to fix, kept up to date.

Two sources:

- the workspace's `deckz status` (the content checks, what its changes leave
  to translate, labs and videos not published), run by the workspace's own
  deckz in the background, and again whenever the workspace's files changed
  since (`git status`, about 20 ms): the checks take some 10 s on a large
  repository;
- the deck on screen: its live build's failure (`studioz.watches`), and the
  frames its last build shrank to fit the page (`deckz.analyzing.overflow`,
  from what the build recorded).

Each problem names the file, and line, it's about when it can, so that a
page can open it in the editor.
"""

import json
import os
import re
import signal
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, Thread

from deckz.analyzing.overflow import shrunk_frames
from deckz.configuring.settings import DeckSettings
from deckz.exceptions import DeckzError
from deckz.models import Lang

from . import sources
from .watches import Snapshot, State, environment

# `deckz status`'s sections shown, by key. Its built decks not matching their
# content are for building and uploading, not a problem while editing (and
# `status_command` doesn't ask for them).
_TITLES = {
    "checks": "Vérifications",
    "translation": "Traduction",
    "labs": "Labs",
    "videos": "Vidéos",
}
_LOCATION = re.compile(r"(?P<file>[^\s:'\"`()]+\.(?:md|yml))(?::(?P<line>\d+))?")
_TIMEOUT = 600


@dataclass(frozen=True)
class Problem:
    text: str
    fix: str = ""
    """How to resolve it, when deckz says."""
    file: str | None = None
    """The workspace's file it's about, one the editor opens."""
    line: int | None = None
    page: int | None = None
    """The page of the deck's handout it's about."""


@dataclass(frozen=True)
class Group:
    title: str
    problems: tuple[Problem, ...]


@dataclass(frozen=True)
class StatusReport:
    groups: tuple[Group, ...]
    """The sections with problems, in `deckz status`'s order."""
    running: bool
    """Whether a run is under way, whose result will replace this one."""
    checked: datetime | None
    """When the run reported finished, None before the first one."""
    error: str | None = None
    """Why the last run failed."""


def locate(workspace: Path, text: str) -> tuple[str | None, int | None]:
    """The first file `text` names that the editor opens, and its line.

    Returns:
        The file, relative to the workspace, and the line if named, or \
        `(None, None)`.
    """
    for match in _LOCATION.finditer(text):
        file = match["file"]
        if Path(file).is_absolute():
            try:
                file = Path(file).relative_to(workspace).as_posix()
            except ValueError:
                continue
        if sources.source(workspace, file) is not None:
            return file, int(match["line"]) if match["line"] else None
    return None, None


def _git(workspace: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _fingerprint(workspace: Path) -> tuple[str, ...]:
    """What `deckz status` depends on.

    Returns:
        HEAD, and each changed file's status, time and size.
    """
    status = _git(workspace, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    changed = []
    for entry in (status or "").split("\0"):
        path = workspace / entry[3:]
        try:
            stat = path.stat()
        except OSError:
            changed.append(entry)
            continue
        changed.append(f"{entry}\0{stat.st_mtime_ns}\0{stat.st_size}")
    return (_git(workspace, "rev-parse", "HEAD") or "", *changed)


def status_command(workspace: Path, since: str | None) -> list[str]:
    """`deckz status` of a workspace, by its own deckz.

    Returns:
        The command, to run in the workspace.
    """
    # The built decks, slow to compare, aren't shown (`_TITLES`).
    deckz = str(workspace / ".venv" / "bin" / "deckz")
    command = [deckz, "status", "--json", "--no-decks"]
    return [*command, "--since", since] if since else command


def _groups(workspace: Path, sections: list[dict]) -> tuple[Group, ...]:
    groups = []
    for section in sections:
        title = _TITLES.get(section.get("key", ""))
        if title is None or not section["items"]:
            continue
        problems = []
        for item in section["items"]:
            file, line = locate(workspace, item["text"])
            problems.append(Problem(item["text"], item.get("fix", ""), file, line))
        groups.append(Group(title, tuple(problems)))
    return tuple(groups)


@dataclass
class _Run:
    fingerprint: tuple[str, ...] | None = None
    process: subprocess.Popen[str] | None = None
    report: StatusReport = field(
        default_factory=lambda: StatusReport((), running=False, checked=None)
    )


class Statuses:
    """Each workspace's `deckz status`, run again when its files change."""

    def __init__(self, base: str | None, command=status_command) -> None:
        """Prepare the runs.

        Args:
            base: What workspaces' changes are counted from (their merge \
                base with it): the branch they sync with.
            command: `status_command`, which tests replace.
        """
        self._base = base
        self._command = command
        self._runs: dict[Path, _Run] = {}
        self._lock = Lock()

    def report(self, workspace: Path) -> StatusReport:
        """The workspace's last status, starting a new run if it changed since.

        Returns:
            The last run's report, `running` if a new one is under way.
        """
        fingerprint = _fingerprint(workspace)
        with self._lock:
            run = self._runs.setdefault(workspace, _Run())
            if run.fingerprint != fingerprint and not run.report.running:
                run.fingerprint = fingerprint
                run.report = StatusReport(
                    run.report.groups, True, run.report.checked, run.report.error
                )
                Thread(target=self._run, args=(workspace, run), daemon=True).start()
            return run.report

    def _run(self, workspace: Path, run: _Run) -> None:
        since = (
            _git(workspace, "merge-base", "HEAD", self._base) if self._base else None
        )
        try:
            process = subprocess.Popen(
                self._command(workspace, since),
                cwd=workspace,
                env=environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except OSError as error:
            self._finish(run, None, str(error))
            return
        with self._lock:
            run.process = process
        try:
            out, err = process.communicate(timeout=_TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            out, err = process.communicate()
        try:
            sections = json.loads(out)["sections"]
        except (json.JSONDecodeError, KeyError, TypeError):
            lines = (err or out).strip().splitlines()
            self._finish(
                run, None, lines[-1] if lines else f"code {process.returncode}"
            )
            return
        self._finish(run, _groups(workspace, sections), None)

    def _finish(
        self, run: _Run, groups: tuple[Group, ...] | None, error: str | None
    ) -> None:
        with self._lock:
            run.process = None
            run.report = StatusReport(
                run.report.groups if groups is None else groups,
                running=False,
                checked=datetime.now(UTC),
                error=error,
            )

    def stop_all(self) -> None:
        with self._lock:
            processes = [run.process for run in self._runs.values() if run.process]
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)


def build_problems(workspace: Path, snapshot: Snapshot) -> Group | None:
    """The live build's failure, if it failed.

    Returns:
        Its group, None unless the last build failed.
    """
    if snapshot.state is not State.FAILED or not snapshot.errors:
        return None
    text = "\n".join(snapshot.errors)
    file, line = locate(workspace, text)
    # deckz names files by their absolute path.
    text = text.replace(f"{workspace}/", "")
    return Group("Construction", (Problem(text, file=file, line=line),))


def _ratio(ratio: str) -> str:
    return ratio.replace("%", " %").replace(".", ",")


def shrunk(workspace: Path, deck: Path, lang: Lang) -> Group | None:
    """The frames the deck's last handout build shrank to fit their page.

    Returns:
        Their group, None if there's none or no build recorded them.
    """
    try:
        found = shrunk_frames(DeckSettings.from_yaml(deck), lang=lang, query=False)
    except DeckzError:
        return None
    problems = []
    for frame in found:
        file = frame.sources[0] if len(frame.sources) == 1 else None
        if file is not None and sources.source(workspace, file) is None:
            file = None
        problems.append(
            Problem(
                f"p. {frame.page} « {frame.title} » réduit à {_ratio(frame.ratio)}",
                file=file,
                line=frame.line if file else None,
                page=frame.page,
            )
        )
    return Group("Cadres réduits pour tenir", tuple(problems)) if problems else None
