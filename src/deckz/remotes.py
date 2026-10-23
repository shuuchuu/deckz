"""The git remotes `deckz labs publish` and `deckz videos publish` push to.

A clone has them only once someone adds them (`git clone` brings `origin`
alone): `deckz.yml`'s `setup.remotes` lists their URLs, so that `deckz
setup` adds the missing ones, and a publish names the fix when one is
missing, can't be reached, or refuses the push, instead of failing on git's
exit code alone.

Shells out to `git`, which picks up the user's own credentials and ssh agent.
"""

import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from .exceptions import RemoteError

if TYPE_CHECKING:
    from .configuring.settings import GlobalSettings


def _run(git_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(git_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def remote_url(git_dir: Path, remote: str) -> str | None:
    """The URL of `git_dir`'s remote `remote`.

    Returns:
        The URL, or None if the clone has no such remote.
    """
    result = _run(git_dir, "remote", "get-url", remote)
    return None if result.returncode else result.stdout.strip()


def add_remote_fix(remote: str, url: str | None) -> str:
    """How to add the missing remote `remote`, whose URL `setup.remotes` may give.

    Returns:
        The fix.
    """
    if url:
        return f"`deckz setup` adds it (`git remote add {remote} {url}`)"
    return (
        f"`git remote add {remote} <its URL>`, and list it in `deckz.yml`'s "
        "`setup.remotes` so that `deckz setup` adds it in every clone"
    )


def publish_remotes(settings: "GlobalSettings", what: str) -> tuple[str, ...]:
    """The remotes `deckz <what> publish` pushes to.

    Args:
        settings: The repository's settings.
        what: `labs` or `videos`.

    Returns:
        Their names.
    """
    if what == "videos":
        return (settings.videos.publish_remote,)
    labs = settings.labs
    if labs.published_files_remote:
        return (labs.publish_remote, labs.published_files_remote)
    return (labs.publish_remote,)


def require_remotes(settings: "GlobalSettings", remotes: Iterable[str]) -> None:
    """Make sure the clone has each of `remotes`, before anything is fetched.

    Raises:
        RemoteError: Naming each missing one, and how to add it.
    """
    git_dir = settings.paths.git_dir
    missing = [r for r in remotes if remote_url(git_dir, r) is None]
    if missing:
        fixes = "; ".join(
            f"no `{r}` remote in this clone: "
            + add_remote_fix(r, settings.setup.remotes.get(r))
            for r in missing
        )
        raise RemoteError(fixes)


def _failure(action: str, remote: str, result: subprocess.CompletedProcess[str]) -> str:
    # git's own message says what failed: no such remote, ssh refusing the key,
    # no write access, a rejected push.
    stderr = result.stderr.strip() or f"git exited {result.returncode}"
    return (
        f"can't {action} {remote}: {stderr}\n"
        f"Check that `git ls-remote {remote}` works (ssh key, network), and "
        "that your GitHub account may push to the repository"
    )


def branch_tip(git_dir: Path, remote: str, branch: str) -> str | None:
    """Fetch `remote`'s `branch`, if it already exists.

    Returns:
        Its commit, or None before the first publish.

    Raises:
        RemoteError: If `remote` can't be reached, or the fetch fails.
    """
    listed = _run(git_dir, "ls-remote", "--heads", remote, branch)
    if listed.returncode:
        raise RemoteError(_failure("reach", remote, listed))
    if not listed.stdout.strip():
        return None
    fetched = _run(git_dir, "fetch", "--quiet", remote, branch)
    if fetched.returncode:
        raise RemoteError(_failure("fetch from", remote, fetched))
    return _run(git_dir, "rev-parse", f"{remote}/{branch}").stdout.strip()


def replace_branch(
    git_dir: Path, remote: str, branch: str, commit: str, tip: str | None
) -> None:
    """Force-push `commit` to `remote`'s `branch`, provided it's still at `tip`.

    Args:
        git_dir: The repository.
        remote: The remote to push to.
        branch: Its branch to replace.
        commit: The commit it becomes.
        tip: The commit `branch_tip` found, None if there was none: the push \
            fails if the branch moved since (`--force-with-lease`).

    Raises:
        RemoteError: If the push fails.
    """
    pushed = _run(
        git_dir,
        "push",
        f"--force-with-lease={branch}:{tip or ''}",
        remote,
        f"{commit}:refs/heads/{branch}",
    )
    if pushed.returncode:
        raise RemoteError(_failure("push to", remote, pushed))
