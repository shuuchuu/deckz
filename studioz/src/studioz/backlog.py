"""The translation backlog: what `deckz i18n stale` says is left to port.

A file is stale when commits changed it after its other-language sibling's
last change (deckz's rule, from git history alone): it depends on the
workspace's commits only, so it's found again when HEAD moves.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from .background import Runs, git


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

    def __init__(self, command=stale_command) -> None:
        """Prepare the runs.

        Args:
            command: `stale_command`, which tests replace.
        """
        super().__init__(command, _parse, _head)


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
