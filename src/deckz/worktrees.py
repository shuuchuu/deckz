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

`land` rebases a worktree's branch onto the main checkout's, then
fast-forwards the main checkout to it: the history stays linear.

`remove` refuses while the worktree holds work nothing else has:
uncommitted changes, or commits on no other branch, local or remote.

A worktree's builds outlive it (`hand_over`): `land` and `remove` copy into
the main checkout the stamped outputs under `worktree.seed` it lacks, and
`remove` sets aside in the repository's git directory those the main
checkout holds stamped otherwise (`deckz.stamps.set_aside`). Only a builder
knows which stamp its sources digest to now, so neither is overwritten: the
main checkout's builders adopt the one set aside once their sources digest
to its stamp (a pull of the worktree's commits), or `deckz setup` drops it
after `deckz.stamps.STORE_DAYS`.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from shutil import copy2
from typing import TYPE_CHECKING

from .exceptions import WorktreeError
from .stamps import held_elsewhere, set_aside, stamp_path, write_stamp
from .utils import copy_file_if_changed

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


@dataclass(frozen=True)
class Renders:
    """What `hand_over` does with a worktree's builds: paths in the checkout."""

    copied: tuple[str, ...] = ()
    """Copied into the main checkout, which lacked them."""
    set_aside: tuple[str, ...] = ()
    """Kept in the repository's git directory, the main checkout's own \
    copy being stamped otherwise."""


@dataclass(frozen=True)
class Removed:
    kept_branch: bool
    """Whether its branch was kept, for its unsynced commits."""
    renders: Renders


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


def hand_over(
    source: Path,
    main: Path,
    entries: tuple[str, ...],
    *,
    store: bool,
    dry_run: bool = False,
) -> Renders:
    """Give the main checkout `source`'s stamped builds under `entries`.

    Each stamped output (`deckz.stamps`) the main checkout lacks is copied \
    there, its companions (the files beside it named after it, e.g. a \
    video's poster) first and its stamp last. With `store`, each the main \
    checkout holds stamped otherwise is set aside (`deckz.stamps.set_aside`), \
    unless another checkout or the store holds it with the same stamp. One \
    stamped the same in both is left alone.

    Args:
        source: The worktree.
        main: The main checkout.
        entries: `deckz.yml`'s `worktree.seed`.
        store: Set aside what the main checkout holds stamped otherwise.
        dry_run: Only say what would be done.

    Returns:
        What was (or would be) copied and set aside.
    """
    if not entries or not source.is_dir():
        return Renders()
    copied, kept = [], []
    for output, companions in _stamped_builds(source, entries):
        stamp = (source / stamp_path(output)).read_text(encoding="utf8").strip()
        mine = main / output
        if not mine.is_file():
            copied.append(str(output))
            if not dry_run:
                _copy_build(source, main, output, companions, stamp)
        elif (
            store
            and _read(stamp_path(mine)) != stamp
            and not held_elsewhere(source, output, stamp)
        ):
            kept.append(str(output))
            if not dry_run:
                set_aside(
                    source, source / output, [source / file for file in companions]
                )
    return Renders(tuple(copied), tuple(kept))


def _stamped_builds(
    checkout: Path, entries: tuple[str, ...]
) -> list[tuple[Path, list[Path]]]:
    """The stamped outputs among `checkout`'s ignored files under `entries`.

    Returns:
        Each output and its companions (the files beside it named after it, \
        e.g. a video's poster and quality), relative to `checkout`, sorted.
    """
    listed = _git(
        checkout,
        "ls-files",
        "-z",
        "--others",
        "--ignored",
        "--exclude-standard",
        "--",
        *entries,
    )
    files = {Path(file) for file in listed.split("\0") if file}
    outputs = {
        file.with_name(file.name.removesuffix(".stamp"))
        for file in files
        if file.name.endswith(".stamp")
    }
    by_dir: dict[Path, list[Path]] = {}
    for file in files - outputs:
        if not file.name.endswith(".stamp"):
            by_dir.setdefault(file.parent, []).append(file)
    return [
        (
            output,
            sorted(
                file
                for file in by_dir.get(output.parent, ())
                if file.name.startswith(f"{output.stem}.")
            ),
        )
        for output in sorted(outputs & files)
    ]


def _copy_build(
    source: Path, main: Path, output: Path, companions: list[Path], stamp: str
) -> None:
    """Copy `output` and its companions from `source` to `main`, its stamp last."""
    # Its stamp, if left, isn't about the files copied.
    stamp_path(main / output).unlink(missing_ok=True)
    for file in (*companions, output):
        copy_file_if_changed(source / file, main / file)
    write_stamp(main / output, stamp)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf8").strip()
    except OSError:
        return None


def pending_renders(settings: "GlobalSettings", name: str) -> Renders:
    """What `remove` would do with the worktree `name`'s builds.

    Returns:
        Them, nothing done; nothing for an unknown worktree.
    """
    worktree = next((w for w in worktrees(settings) if w.name == name), None)
    if worktree is None:
        return Renders()
    main = main_checkout(settings.paths.git_dir)
    return hand_over(
        worktree.path, main, settings.worktree.seed, store=True, dry_run=True
    )


def remove(settings: "GlobalSettings", name: str, *, force: bool = False) -> Removed:
    """Remove the worktree `name`, and its branch unless it has unsynced commits.

    Its builds go to the main checkout first (`hand_over`).

    Args:
        settings: The settings of any checkout of the repository.
        name: The worktree's name.
        force: Remove it even with uncommitted changes (lost) or unsynced \
            commits (kept on its branch).

    Returns:
        Whether its branch was kept, and what became of its builds.

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
    renders = hand_over(worktree.path, main, settings.worktree.seed, store=True)
    _git(
        main, "worktree", "remove", *(["--force"] if force else []), str(worktree.path)
    )
    if worktree.unsynced:
        return Removed(kept_branch=True, renders=renders)
    _git(main, "branch", "-D", worktree.branch)
    return Removed(kept_branch=False, renders=renders)


def land(
    settings: "GlobalSettings", name: str | None = None
) -> tuple[str, int, Renders]:
    """Put the worktree `name`'s commits on the main checkout's branch.

    Rebases its branch onto the main checkout's (linear history), then
    fast-forwards the main checkout to it, which updates the main checkout's
    files: git refuses if one of them has an uncommitted change there. Then
    the worktree's builds the main checkout lacks are copied there
    (`hand_over`).

    Args:
        settings: The settings of any checkout of the repository.
        name: The worktree's name; None for the one running the command.

    Returns:
        The main checkout's branch, how many commits it gained, and the \
        builds copied.

    Raises:
        WorktreeError: If there's no such worktree, the rebase conflicts or \
            the fast-forward is refused.
    """
    found = {w.name: w for w in worktrees(settings)}
    if name is None:
        here = settings.paths.git_dir.resolve()
        name = next((n for n, w in found.items() if w.path.resolve() == here), None)
        if name is None:
            msg = "not in a worktree: name the one to land"
            raise WorktreeError(msg)
    if name not in found:
        names = ", ".join(found) or "none"
        msg = f"no worktree named {name!r} (worktrees: {names})"
        raise WorktreeError(msg)
    worktree = found[name]
    main = main_checkout(settings.paths.git_dir)
    target = _git(main, "symbolic-ref", "--short", "HEAD").strip()
    try:
        _git(worktree.path, "rebase", "--quiet", target)
    except WorktreeError as error:
        subprocess.run(
            ["git", "-C", str(worktree.path), "rebase", "--abort"],
            capture_output=True,
            check=False,
        )
        msg = (
            f"rebasing {worktree.branch} onto {target} failed ({error}): commit "
            f"its uncommitted changes, or rebase by hand (`git rebase {target}` "
            f"in {worktree.path}), resolve the conflicts, and land again"
        )
        raise WorktreeError(msg) from error
    count = int(_git(main, "rev-list", "--count", f"HEAD..{worktree.branch}"))
    try:
        _git(main, "merge", "--quiet", "--ff-only", worktree.branch)
    except WorktreeError as error:
        msg = (
            f"fast-forwarding {target} in {main} was refused ({error}): an "
            "uncommitted change there touches one of the landed files"
        )
        raise WorktreeError(msg) from error
    renders = hand_over(worktree.path, main, settings.worktree.seed, store=False)
    return target, count, renders


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
