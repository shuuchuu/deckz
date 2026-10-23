"""The branch everyone's work meets on: the main checkout's upstream.

Labs and videos are published from it (`origin/main` on slides), not from
the checkout a publish runs in: a worktree branched days earlier, or a
checkout not pulled since, would otherwise put older notebooks back in
place of newer ones (it happened on 2026-10-23). A worktree's own branch
(`ws/<name>`) has no upstream of its own: every checkout of a repository
publishes from its main checkout's branch's upstream.

Shells out to `git`, which picks up the user's own credentials and ssh agent.
"""

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .exceptions import RemoteError


@dataclass(frozen=True)
class Upstream:
    remote: str
    branch: str
    """The remote's branch, e.g. `main`."""
    tracking: str
    """Its remote-tracking ref, e.g. `refs/remotes/origin/main`."""

    @property
    def name(self) -> str:
        return f"{self.remote}/{self.branch}"


def _run(git_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(git_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _git(git_dir: Path, *args: str) -> str:
    result = _run(git_dir, *args)
    return "" if result.returncode else result.stdout.strip()


def upstream(git_dir: Path) -> Upstream | None:
    """The upstream of the branch `git_dir`'s main checkout is on.

    Returns:
        It, None when that branch has none (or the main checkout isn't on a \
        branch).
    """
    from .worktrees import main_checkout

    main = main_checkout(git_dir)
    branch = _git(main, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch:
        return None
    found = _git(
        main,
        "for-each-ref",
        "--format=%(upstream:remotename)%00%(upstream:remoteref)%00%(upstream)",
        f"refs/heads/{branch}",
    )
    parts = found.split("\0")
    if len(parts) != 3 or not all(parts):
        return None
    remote, ref, tracking = parts
    return Upstream(remote, ref.removeprefix("refs/heads/"), tracking)


def fetch(git_dir: Path, up: Upstream) -> str:
    """Fetch `up`'s branch.

    Returns:
        Its commit.

    Raises:
        RemoteError: If the fetch fails, with git's message and what to check.
    """
    fetched = _run(git_dir, "fetch", "--quiet", up.remote, up.branch)
    if fetched.returncode:
        stderr = fetched.stderr.strip() or f"git exited {fetched.returncode}"
        msg = (
            f"can't fetch {up.name}: {stderr}\n"
            f"Check that `git ls-remote {up.remote}` works (ssh key, network)"
        )
        raise RemoteError(msg)
    return _git(git_dir, "rev-parse", up.tracking)


@dataclass(frozen=True)
class Source:
    """The commit a publish takes its files from."""

    commit: str
    name: str
    """How to name it to a person: `origin/main`, or `HEAD`."""
    upstream: Upstream | None
    """Where it comes from; None when the repository has no upstream (HEAD)."""


def source(git_dir: Path, *, fetch_first: bool = True) -> Source:
    """What to publish from: the upstream branch, or HEAD when there's none.

    A failing fetch raises `fetch`'s `RemoteError`.

    Args:
        git_dir: Any checkout of the repository.
        fetch_first: Fetch the upstream branch first; else take it as last \
            fetched (HEAD when it never was).

    Returns:
        The source.
    """
    up = upstream(git_dir)
    if up is not None:
        if fetch_first:
            return Source(fetch(git_dir, up), up.name, up)
        if commit := _git(git_dir, "rev-parse", "--verify", "--quiet", up.tracking):
            return Source(commit, up.name, up)
    return Source(_git(git_dir, "rev-parse", "HEAD"), "HEAD", None)


def unpushed(git_dir: Path, base: str, paths: Iterable[str]) -> list[str]:
    """HEAD's commits touching `paths` that `base` lacks.

    Returns:
        Each one as `<short sha> <subject>`, newest first.
    """
    listed = _git(git_dir, "log", "--format=%h %s", f"{base}..HEAD", "--", *paths)
    return listed.splitlines()


def missing(git_dir: Path, base: str, paths: Iterable[str]) -> list[str]:
    """`base`'s commits touching `paths` that HEAD lacks (an update brings them).

    Returns:
        Each one as `<short sha> <subject>`, newest first.
    """
    listed = _git(git_dir, "log", "--format=%h %s", f"HEAD..{base}", "--", *paths)
    return listed.splitlines()


def known_blobs(git_dir: Path, commit: str, paths: Iterable[str]) -> set[str]:
    """Every object of `commit`'s history under `paths`, its files' versions included.

    Returns:
        Their shas (commits and trees too: a blob sha is never one of them).
    """
    listed = _git(git_dir, "rev-list", "--objects", commit, "--", *paths)
    return {line.split(" ", 1)[0] for line in listed.splitlines()}
