"""Worktrees as workspaces: what `deckz worktree` does.

A worktree is a second checkout of the repository on its own branch, sharing
the main checkout's history: work on one deck there doesn't disturb builds,
PDFs or uncommitted edits in the main checkout, or in another worktree.
deckz resolves every path from the checkout it runs in, so each worktree
builds on its own.

`add` creates `../<repo>--<name>` on a new `ws/<name>` branch and copies into
it the builds a fresh checkout lacks (the main checkout's ignored files under
`deckz.yml`'s `worktree.seed`, e.g. rendered figures and videos). Copies keep
their file times, so that a build's content stamps (`deckz.stamps`) decide
what to rebuild: a copied output whose source differs in the worktree is
rebuilt, and one with no stamp looks older than the fresh checkout's
sources, so it's rebuilt rather than adopted. Nothing is linked: each
checkout has its own environment (`deckz setup` there, e.g. `uv sync`, takes
a second from uv's cache), and what every checkout shares (credentials, one's
own defaults) goes in the user's `.env` (see `deckz.cli.main`).

`remove` refuses while the worktree holds work nothing else has:
uncommitted changes, or commits on no other branch, local or remote.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from shutil import copy2
from typing import TYPE_CHECKING

from .exceptions import WorktreeError

if TYPE_CHECKING:
    from .configuring.settings import GlobalSettings

BRANCH_PREFIX = "ws/"
"""Prefix of every worktree's branch, `ws/<name>`."""

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_SHOWN_CHANGES = 20


@dataclass(frozen=True)
class Worktree:
    name: str
    path: Path
    branch: str
    changes: tuple[str, ...]
    """Uncommitted changes, as `git status --porcelain` lines."""
    unsynced: int
    """Commits on its branch that no other branch, local or remote, has."""


@dataclass(frozen=True)
class AddedWorktree:
    path: Path
    branch: str
    base: str
    """The commit it starts from."""
    copied: int
    """How many files were copied from the main checkout."""


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False
    )
    if result.returncode:
        msg = f"git {' '.join(args)} failed: {result.stderr.strip()}"
        raise WorktreeError(msg)
    return result.stdout


def main_checkout(git_dir: Path) -> Path:
    """The repository's main checkout, from any of its checkouts.

    Returns:
        Its root.
    """
    first = _git(git_dir, "worktree", "list", "--porcelain").splitlines()[0]
    return Path(first.removeprefix("worktree "))


def worktree_path(main: Path, name: str) -> Path:
    """Where the worktree `name` goes: next to the main checkout.

    Next to it rather than under it, so that relative paths out of the \
    repository (e.g. a uv path dependency on `../deckz`) resolve the same.

    Returns:
        `<main's parent>/<main's name>--<name>`.
    """
    return main.parent / f"{main.name}--{name}"


def worktrees(settings: "GlobalSettings") -> list[Worktree]:
    """Every worktree on a `ws/` branch, or rebasing one.

    Returns:
        Them, in `git worktree list`'s order.
    """
    main = main_checkout(settings.paths.git_dir)
    found = []
    for block in _git(main, "worktree", "list", "--porcelain").split("\n\n"):
        fields = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        if "worktree" not in fields:
            continue
        path = Path(fields["worktree"])
        branch = fields.get("branch") or _rebased_branch(path) or ""
        branch = branch.removeprefix("refs/heads/")
        if not branch.startswith(BRANCH_PREFIX):
            continue
        changes = (
            tuple(_git(path, "status", "--porcelain").splitlines())
            if path.is_dir()
            else ()
        )
        found.append(
            Worktree(
                name=branch.removeprefix(BRANCH_PREFIX),
                path=path,
                branch=branch,
                changes=changes,
                unsynced=_unsynced(main, branch),
            )
        )
    return found


def _rebased_branch(path: Path) -> str | None:
    """The branch a rebase in `path` is on: its HEAD is detached until it ends.

    Returns:
        Its ref, None outside a rebase.
    """
    for state in ("rebase-merge", "rebase-apply"):
        try:
            located = _git(path, "rev-parse", "--git-path", f"{state}/head-name")
        except WorktreeError:
            return None
        head_name = path / located.strip()
        if head_name.is_file():
            return head_name.read_text(encoding="utf8").strip()
    return None


def _unsynced(main: Path, branch: str) -> int:
    return int(
        _git(
            main,
            "rev-list",
            "--count",
            f"refs/heads/{branch}",
            "--not",
            f"--exclude={branch}",
            "--branches",
            "--remotes",
        )
    )


def add(
    settings: "GlobalSettings", name: str, base: str | None = None
) -> AddedWorktree:
    """Create the worktree `name`, and bring in the builds and shared files.

    Args:
        settings: The settings of any checkout of the repository.
        name: The worktree's name: letters, digits, `-` and `_`.
        base: The revision to start from; the main checkout's `HEAD` if None.

    Returns:
        What was created, copied and linked.

    Raises:
        WorktreeError: If `name` is invalid or taken, or `base` unknown.
    """
    if not _NAME.fullmatch(name):
        msg = f"invalid worktree name {name!r}: use letters, digits, - and _"
        raise WorktreeError(msg)
    main = main_checkout(settings.paths.git_dir)
    path = worktree_path(main, name)
    branch = BRANCH_PREFIX + name
    if path.exists():
        msg = f"{path} already exists"
        raise WorktreeError(msg)
    if _git(main, "branch", "--list", branch).strip():
        msg = f"branch {branch} already exists: pick another name"
        raise WorktreeError(msg)
    sha = _git(main, "rev-parse", "--verify", f"{base or 'HEAD'}^{{commit}}").strip()
    _git(main, "worktree", "add", "--quiet", "-b", branch, str(path), sha)
    copied = seed(main, path, settings.worktree.seed)
    return AddedWorktree(path, branch, sha, copied)


def seed(source: Path, path: Path, entries: tuple[str, ...]) -> int:
    """Copy `source`'s ignored files under `entries` into the checkout `path`.

    What `add` does with `deckz.yml`'s `worktree.seed`; also for other \
    checkouts, e.g. a scratch one seeded from a worktree.

    Returns:
        How many files were copied.
    """
    if not entries:
        return 0
    listed = _git(
        source,
        "ls-files",
        "-z",
        "--others",
        "--ignored",
        "--exclude-standard",
        "--",
        *entries,
    )
    files = [file for file in listed.split("\0") if file]
    for file in files:
        destination = path / file
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Times kept: see the module docstring.
        copy2(source / file, destination, follow_symlinks=False)
    return len(files)


def remove(settings: "GlobalSettings", name: str, *, force: bool = False) -> bool:
    """Remove the worktree `name`, and its branch unless it has unsynced commits.

    Args:
        settings: The settings of any checkout of the repository.
        name: The worktree's name.
        force: Remove it even with uncommitted changes (lost) or unsynced \
            commits (kept on its branch).

    Returns:
        Whether its branch was kept, for its unsynced commits.

    Raises:
        WorktreeError: If there's no such worktree, it's the one running \
            the command, or it holds work only it has and not `force`.
    """
    found = {w.name: w for w in worktrees(settings)}
    if name not in found:
        names = ", ".join(found) or "none"
        msg = f"no worktree named {name!r} (worktrees: {names})"
        raise WorktreeError(msg)
    worktree = found[name]
    if settings.paths.git_dir.resolve() == worktree.path.resolve():
        msg = f"run it from another checkout than {worktree.path}"
        raise WorktreeError(msg)
    if (worktree.changes or worktree.unsynced) and not force:
        raise WorktreeError(_refusal(worktree))
    main = main_checkout(settings.paths.git_dir)
    _git(
        main, "worktree", "remove", *(["--force"] if force else []), str(worktree.path)
    )
    if worktree.unsynced:
        return True
    _git(main, "branch", "-D", worktree.branch)
    return False


def _refusal(worktree: Worktree) -> str:
    problems = []
    if worktree.changes:
        shown = [f"    {line}" for line in worktree.changes[:_SHOWN_CHANGES]]
        if len(worktree.changes) > _SHOWN_CHANGES:
            shown.append(f"    ... and {len(worktree.changes) - _SHOWN_CHANGES} more")
        problems.append("- uncommitted changes:\n" + "\n".join(shown))
    if worktree.unsynced:
        problems.append(
            f"- {worktree.unsynced} commit(s) on {worktree.branch} that no other "
            "branch has"
        )
    return (
        f"{worktree.path} holds work nothing else has:\n"
        + "\n".join(problems)
        + "\nCommit and sync it, or pass --force (uncommitted changes are lost, "
        "commits stay on their branch)"
    )
