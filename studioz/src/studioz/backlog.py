"""The translation backlog: what `deckz i18n stale` says is left to port.

A file is stale when commits changed it after its other-language sibling's
last change (deckz's rule, from git history alone): it depends on the
workspace's commits only, so it's found again when HEAD moves. When its
changes need no port after all, `deckz i18n mark-synced` records it in an
empty commit, which the person makes from the panel ("Rien à porter…").
"""

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .background import Runs, git
from .watches import workspace_environment

_MARK_TIMEOUT = 120


@dataclass(frozen=True)
class Stale:
    """A file whose changes its sibling hasn't followed."""

    path: str
    sibling: str
    since: str | None
    """The sibling's last commit before them, None if it never changed."""
    subjects: tuple[str, ...]
    """The commits to port, oldest first."""


def stale_command(workspace: Path) -> list[str]:
    """`deckz i18n stale` of a workspace, by its own deckz.

    Returns:
        The command, to run in the workspace.
    """
    return [str(workspace / ".venv" / "bin" / "deckz"), "i18n", "stale", "--json"]


def mark_command(workspace: Path, path: str, reason: str) -> list[str]:
    """`deckz i18n mark-synced` of a workspace, by its own deckz.

    Returns:
        The command, to run in the workspace.
    """
    return [
        str(workspace / ".venv" / "bin" / "deckz"),
        "i18n",
        "mark-synced",
        path,
        "--reason",
        reason,
    ]


@dataclass(frozen=True)
class Marked:
    """`deckz i18n mark-synced`'s outcome."""

    ok: bool
    output: str
    """What it said: the pair settled, or why not."""


def _parse(_workspace: Path, output: str) -> tuple[Stale, ...]:
    return tuple(
        Stale(
            item["path"],
            item["sibling"],
            item.get("since"),
            tuple(commit["subject"] for commit in item["commits"]),
        )
        for item in json.loads(output)["stale"]
    )


def _head(workspace: Path) -> tuple[str, ...]:
    return (git(workspace, "rev-parse", "HEAD") or "",)


class Backlog(Runs[tuple[Stale, ...]]):
    """Each workspace's translation backlog, found again when its HEAD moves."""

    def __init__(
        self,
        command: Callable[[Path], list[str]] = stale_command,
        mark: Callable[[Path, str, str], list[str]] = mark_command,
    ) -> None:
        """Prepare the runs.

        Args:
            command: `stale_command`, which tests replace.
            mark: `mark_command`, which tests replace.
        """
        super().__init__(command, _parse, _head)
        self._mark = mark

    def find(self, workspace: Path, path: str) -> Stale | None:
        """The backlog's entry for `path`, as last found.

        Returns:
            It, None if the backlog doesn't list it (or isn't found yet).
        """
        stale = self.report(workspace).result or ()
        return next((entry for entry in stale if entry.path == path), None)

    def mark_synced(self, workspace: Path, path: str, reason: str) -> Marked:
        """Record that `path`'s changes need no port: an empty commit, by deckz.

        Returns:
            Whether deckz made it, and what it said (its refusal, typically).
        """
        try:
            result = subprocess.run(
                self._mark(workspace, path, reason),
                cwd=workspace,
                env=workspace_environment(workspace),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                timeout=_MARK_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return Marked(ok=False, output=str(error))
        return Marked(ok=result.returncode == 0, output=result.stdout.strip())


def catching_up(alone: list[str], backlog: tuple[Stale, ...]) -> list[Stale]:
    """The backlog's files whose port `alone` (one-sided changes) would be.

    Returns:
        Their entries, when every path in `alone` is a stale file's \
        sibling; none otherwise.
    """
    ported = {stale.sibling: stale for stale in backlog}
    if not alone or any(path not in ported for path in alone):
        return []
    return [ported[path] for path in alone]
