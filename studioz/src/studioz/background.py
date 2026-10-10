"""Commands run in the background for a workspace, again when it changes.

Some of what a page shows takes seconds to compute (`deckz status`, the
decks a change reaches): each workspace's last result is shown at once, and
a new run starts when what it depends on changed since the last one (its
fingerprint, from `git status`, about 20 ms). The page polls while a run is
under way.
"""

import os
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, Thread

from .watches import environment

_TIMEOUT = 600


@dataclass(frozen=True)
class Change:
    """A file `git status` lists."""

    path: str
    """Relative to the workspace; for a rename, the new path."""
    status: str
    """Its two-letter `git status --porcelain` status, e.g. ` M` or `??`."""


def git(workspace: Path, *args: str) -> str | None:
    """Run git in `workspace`.

    Returns:
        Its output, stripped, or None if it failed.
    """
    result = subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def changes(workspace: Path) -> list[Change]:
    """The workspace's changes since its last commit, untracked files included.

    Returns:
        Each changed file, in `git status`'s order.
    """
    result = subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    entries = iter(result.stdout.split("\0") if result.returncode == 0 else [])
    found = []
    for entry in entries:
        if not entry:
            continue
        found.append(Change(entry[3:], entry[:2]))
        if "R" in entry[:2] or "C" in entry[:2]:
            # The original path follows a rename or copy.
            next(entries, None)
    return found


def fingerprint(workspace: Path) -> tuple[str, ...]:
    """What the workspace's files look like, cheaply.

    Returns:
        HEAD, and each changed file's status, time and size.
    """
    found = []
    for change in changes(workspace):
        try:
            stat = (workspace / change.path).stat()
        except OSError:
            found.append(f"{change.status} {change.path}")
            continue
        found.append(
            f"{change.status} {change.path}\0{stat.st_mtime_ns}\0{stat.st_size}"
        )
    return (git(workspace, "rev-parse", "HEAD") or "", *found)


@dataclass(frozen=True)
class Report[T]:
    result: T | None
    """The last run's result, None before the first one, or if it failed."""
    running: bool
    """Whether a run is under way, whose result will replace this one."""
    checked: datetime | None
    """When the last run finished, None before the first one."""
    error: str | None = None
    """Why the last run failed."""


@dataclass
class _Run[T]:
    fingerprint: tuple[str, ...] | None = None
    process: subprocess.Popen[str] | None = None
    report: Report[T] = field(
        default_factory=lambda: Report(None, running=False, checked=None)
    )


class Runs[T]:
    """One command per workspace, run again when the workspace changes."""

    def __init__(
        self,
        command: Callable[[Path], list[str] | None],
        parse: Callable[[Path, str], T],
        fingerprint: Callable[[Path], tuple[str, ...]] = fingerprint,
    ) -> None:
        """Prepare the runs.

        Args:
            command: The command to run in a workspace, computed in the \
                background; None when there's nothing to run, which \
                reports None.
            parse: The result, from the command's output, whatever its \
                exit code; raising ValueError (e.g. a JSON error), KeyError \
                or TypeError makes the run failed.
            fingerprint: What the result depends on.
        """
        self._command = command
        self._parse = parse
        self._fingerprint = fingerprint
        self._runs: dict[Path, _Run[T]] = {}
        self._lock = Lock()

    def report(self, workspace: Path) -> Report[T]:
        """The workspace's last result, starting a new run if it changed since.

        Returns:
            The last run's report, `running` if a new one is under way.
        """
        current = self._fingerprint(workspace)
        with self._lock:
            run = self._runs.setdefault(workspace, _Run())
            if run.fingerprint != current and not run.report.running:
                run.fingerprint = current
                old = run.report
                run.report = Report(old.result, True, old.checked, old.error)
                Thread(target=self._run, args=(workspace, run), daemon=True).start()
            return run.report

    def _run(self, workspace: Path, run: _Run[T]) -> None:
        command = self._command(workspace)
        if command is None:
            self._finish(run, None, None)
            return
        try:
            process = subprocess.Popen(
                command,
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
            # Its output decides, not its exit code (`deckz status` exits 1
            # on problems).
            result = self._parse(workspace, out)
        except (ValueError, KeyError, TypeError):
            lines = (err or out).strip().splitlines()
            self._finish(
                run, None, lines[-1] if lines else f"code {process.returncode}"
            )
            return
        self._finish(run, result, None)

    def _finish(self, run: _Run[T], result: T | None, error: str | None) -> None:
        with self._lock:
            run.process = None
            run.report = Report(
                run.report.result if error else result,
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
