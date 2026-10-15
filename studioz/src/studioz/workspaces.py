"""Workspaces: `deckz worktree`'s worktrees, plus what studioz shows of them.

A workspace is a worktree on a `ws/<name>` branch (`deckz.worktrees`).
studioz adds what its pages show: how far it is behind the upstream branch,
when it was last used, its size, and its decks. Its own state about a
workspace lives in the workspace, under `.run/studioz/`.
"""

import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from os import walk
from pathlib import Path
from typing import TYPE_CHECKING

from deckz.setting_up import incomplete, setup
from deckz.worktrees import (
    BRANCH_PREFIX,
    Worktree,
    add,
    main_checkout,
    worktree_path,
    worktrees,
)

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


def base_branch(main: Path) -> str | None:
    """What workspaces' changes count from: the upstream branch, else main's.

    Returns:
        A branch name, None if the main checkout has no branch checked out.
    """
    branch = _git(main, "rev-parse", "--abbrev-ref", "HEAD")
    return upstream(main) or (branch if branch and branch != "HEAD" else None)


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


def base_name(main: Path) -> str:
    """What a new workspace starts from: the main checkout's commit.

    Returns:
        Its branch and short hash, e.g. `main (ae4ef519)`.
    """
    branch = _git(main, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    return f"{branch} ({_git(main, 'rev-parse', '--short', 'HEAD') or '?'})"


def free_name(main: Path, wanted: str) -> str:
    """A name for a new workspace, from `wanted`, that no workspace has.

    Returns:
        `wanted` made a valid name (letters, digits, `-`, `_`), with a \
        number when taken.
    """
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", wanted).strip("-_")[:40] or "travail"
    for number in range(1, 100):
        name = base if number == 1 else f"{base}-{number}"
        taken = worktree_path(main, name).exists() or _git(
            main, "branch", "--list", BRANCH_PREFIX + name
        )
        if not taken:
            return name
    return f"{base}-{datetime.now(UTC):%Y%m%d%H%M%S}"


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


@dataclass(frozen=True)
class DeckFolder:
    """A folder of the sidebar's deck tree.

    Attributes:
        name: What the tree shows: several folders when each held only the \
            next one (`orsys/INTRA`), as VS Code's compact folders.
        path: Its path relative to the workspace (`decks/orsys/INTRA`).
        folders: Its subfolders holding decks.
        decks: Its decks, each its name and its path relative to the workspace.
    """

    name: str
    path: str
    folders: tuple["DeckFolder", ...]
    decks: tuple[tuple[str, str], ...]


@dataclass
class _Node:
    children: dict[str, "_Node"]
    deck: bool = False


def deck_tree(decks: list[str]) -> DeckFolder:
    """The decks as a tree, for the sidebar.

    The folders every deck shares (`decks/`) are left out: the tree starts
    where they part. A deck holding other decks is both a deck and a folder.

    Returns:
        The tree's root, whose `path` is the folders left out ("" for none).
    """
    root = _Node({})
    for deck in decks:
        node = root
        for part in deck.split("/"):
            node = node.children.setdefault(part, _Node({}))
        node.deck = True
    shared = []
    while len(root.children) == 1 and not root.deck:
        [(name, child)] = root.children.items()
        if child.deck:
            break
        shared.append(name)
        root = child
    return _folder("", "/".join(shared), root)


def _folder(name: str, path: str, node: _Node) -> DeckFolder:
    folders = []
    decks = []
    for child_name, child in sorted(node.children.items()):
        child_path = f"{path}/{child_name}" if path else child_name
        if child.deck:
            decks.append((child_name, child_path))
        if not child.children:
            continue
        label = child_name
        while len(child.children) == 1 and not child.deck:
            [(next_name, next_child)] = child.children.items()
            if next_child.deck:
                break
            label = f"{label}/{next_name}"
            child_path = f"{child_path}/{next_name}"
            child = next_child
        folders.append(_folder(label, child_path, child))
    return DeckFolder(name, path, tuple(folders), tuple(decks))


def deck_dir(path: Path, deck: str) -> Path | None:
    """The workspace's deck directory `deck`, if that's one.

    Returns:
        Its path, None unless `deck` is a relative path within the \
        workspace, through no hidden directory, to a directory with a \
        `deck.yml`.
    """
    parts = Path(deck).parts
    if not parts or Path(deck).is_absolute() or any(p.startswith(".") for p in parts):
        return None
    directory = path / deck
    if not (directory / "deck.yml").is_file():
        return None
    if not directory.resolve().is_relative_to(path.resolve()):
        return None
    return directory
