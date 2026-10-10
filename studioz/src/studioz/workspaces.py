"""Workspaces: `deckz worktree`'s worktrees, plus what studioz shows of them.

A workspace is a worktree on a `ws/<name>` branch (`deckz.worktrees`).
studioz adds what its pages show: how far it is behind the upstream branch,
when it was last used, its size, and its decks. Its own state about a
workspace lives in the workspace, under `.run/studioz/`.
"""

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from os import walk
from pathlib import Path
from typing import TYPE_CHECKING

from deckz.setting_up import incomplete, setup
from deckz.worktrees import BRANCH_PREFIX, Worktree, add, main_checkout, worktrees

if TYPE_CHECKING:
    from deckz.configuring.settings import GlobalSettings
    from deckz.setting_up import SetupItem

STATE_DIR = Path(".run") / "studioz"
"""studioz's own state, relative to a workspace."""

_LAST_USE = STATE_DIR / "last-use"


@dataclass(frozen=True)
class Workspace:
    worktree: Worktree
    behind: int | None
    """Commits of the upstream branch it lacks; None without an upstream."""
    last_use: datetime

    @property
    def name(self) -> str:
        return self.worktree.name


@dataclass(frozen=True)
class Created:
    name: str
    path: Path
    setup: list["SetupItem"]

    @property
    def ready(self) -> bool:
        return not incomplete(self.setup)


def _git(cwd: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False
    )
    return None if result.returncode else result.stdout.strip()


def upstream(main: Path) -> str | None:
    """The branch workspaces sync with: the main checkout's upstream branch.

    Returns:
        Its name (e.g. `origin/main`), None when the main checkout has none.
    """
    return _git(main, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")


def last_use(path: Path) -> datetime:
    """When studioz last opened the workspace, else its last commit's date.

    Returns:
        That time, timezone-aware.
    """
    mark = path / _LAST_USE
    if mark.is_file():
        return datetime.fromtimestamp(mark.stat().st_mtime, UTC)
    committed = _git(path, "log", "-1", "--format=%ct")
    return datetime.fromtimestamp(int(committed or 0), UTC)


def mark_used(path: Path) -> None:
    mark = path / _LAST_USE
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.touch()


def workspaces(settings: "GlobalSettings") -> list[Workspace]:
    """Every workspace of the repository.

    Returns:
        Them, most recently used first.
    """
    main = main_checkout(settings.paths.git_dir)
    branch = upstream(main)
    found = []
    for worktree in worktrees(settings):
        behind = None
        if branch:
            count = _git(main, "rev-list", "--count", f"{worktree.branch}..{branch}")
            behind = int(count) if count else None
        found.append(Workspace(worktree, behind, last_use(worktree.path)))
    return sorted(found, key=lambda w: w.last_use, reverse=True)


def find(settings: "GlobalSettings", name: str) -> Workspace | None:
    return next((w for w in workspaces(settings) if w.name == name), None)


def create(settings: "GlobalSettings", name: str) -> Created:
    """Create the workspace `name`, as `deckz worktree add` does.

    Returns:
        It, with how `deckz setup` went there.
    """
    from deckz.configuring.settings import GlobalSettings

    added = add(settings, name)
    items = setup(GlobalSettings.from_yaml(added.path))
    mark_used(added.path)
    return Created(added.branch.removeprefix(BRANCH_PREFIX), added.path, items)


def size(path: Path) -> int:
    """The disk space closing the workspace would free, ignored builds included.

    Files with other links don't count: its `.venv` is mostly hard links into \
    uv's cache (3 GB counted, 6 MB its own, on slides).

    Returns:
        That size, in bytes.
    """
    total = 0
    for root, _, files in walk(path):
        for file in files:
            try:
                stat = (Path(root) / file).lstat()
            except OSError:
                continue
            if stat.st_nlink == 1:
                total += stat.st_blocks * 512
    return total


def decks(path: Path) -> list[str]:
    """The workspace's decks.

    Returns:
        Each deck directory, relative to the workspace, sorted.
    """
    found = []
    for root, dirs, files in walk(path):
        # Hidden directories hold builds (`.run`) and `.git`/`.venv`.
        dirs[:] = sorted(
            d for d in dirs if not d.startswith(".") and d != "node_modules"
        )
        if "deck.yml" in files:
            found.append(Path(root).relative_to(path).as_posix())
    return found
