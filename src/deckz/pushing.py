"""Push what a session of work leaves local: what `deckz push` does.

In this order:

1. deckz itself, when it runs from a git checkout (an editable install, e.g.
   `../deckz`): its current branch, if it tracks a remote branch and is ahead.
2. The labs' own repositories (`labs.repos`), each from its local clone
   (`labs.repos[].clone`), through copierz (`copierz push --json`, the
   `push` extra): every branch ahead of its remote, and with `force` the
   branches a rebase rewrote, with `--force-with-lease`. Their branches are
   stacked (`solution` on `main`...): a change to a base is rebased into
   the branches above it, which then need a force.
3. The repository itself: its main checkout's branch, if ahead of its
   upstream (`deckz.upstream`).
4. With `publish`, the labs and the videos, when `deckz status` finds
   something left to publish (`deckz.status.unpublished`).

The order matters: the repository's CI installs deckz from its remote, and
its content links to the labs' repositories, so pushing the repository
before them would have its CI check it against a deckz that lacks the code
it depends on. When deckz's push fails, or its branch has diverged from its
remote, nothing after it is pushed. Likewise, the repository's content links
to the labs' repositories' branches: when one of them fails (a push failed,
a branch diverged, a rebased branch left without `force`, copierz failed on
it), the other labs' repositories are still pushed, to show all that blocks
at once, but neither the repository nor any publishing is. A lab repository
merely skipped (no local clone, or not a clone of it; no branch carrying
Copier answers; copierz not installed) doesn't stop it.

Only the labs' branches are ever forced: deckz's and the repository's are
pushed when they're ahead, and left, with the fix, when behind or diverged.
Every branch is compared with its remote once fetched (as last fetched,
offline). `dry_run` fetches, and pushes and publishes nothing.

Git runs as a subprocess, with the user's own credentials and ssh agent.
"""

import json
import subprocess
import sys
from dataclasses import dataclass, field
from importlib.util import find_spec
from os import environ
from os.path import relpath
from pathlib import Path
from typing import TYPE_CHECKING

from .exceptions import DeckzError

if TYPE_CHECKING:
    from .configuring.settings import GlobalSettings, LabRepoSettings


def _env() -> dict[str, str]:
    # Never wait for a password: fail, and say how to fix it.
    return {**environ, "GIT_TERMINAL_PROMPT": "0"}


_FETCH_TIMEOUT = 60
_PUSH_TIMEOUT = 600

PUSHED = "pushed"
WOULD_PUSH = "would push"
UP_TO_DATE = "up to date"
NOT_PUSHED = "not pushed"
FAILED = "failed"


@dataclass(frozen=True)
class BranchPush:
    """What became of one branch."""

    branch: str
    remote: str
    """The remote branch it tracks, e.g. `origin/main`; "" when none."""
    state: str
    """How it stood against its remote: `up_to_date`, `ahead`, `behind`, \
    `diverged`, `no_upstream`, or `rewritten` (a lab's branch a rebase \
    rewrote)."""
    outcome: str
    """`pushed`, `would push` (`dry_run`), `up to date`, `not pushed` or \
    `failed`."""
    commits: int = 0
    """The commits pushed, or that would be."""
    detail: str = ""
    """Why it wasn't pushed and how to fix it, or how it was pushed."""
    problem: bool = False
    """Whether it fails the command: a push failed, or a branch diverged."""


@dataclass(frozen=True)
class RepoPush:
    """What became of one repository's branches."""

    name: str
    """`deckz`, a lab's repository (`owner/name`), or the repository's \
    directory name."""
    kind: str
    """`deckz`, `lab` or `repository`."""
    path: str = ""
    """Its checkout, as shown to a person; "" when it has none."""
    branches: tuple[BranchPush, ...] = ()
    skipped: str = ""
    """Why it wasn't looked at, and the fix, when it wasn't."""
    problem: bool = False
    """Whether it fails the command (one of its branches does, or copierz \
    failed on it)."""


@dataclass(frozen=True)
class PublishResult:
    """What became of the labs, or of the videos."""

    what: str
    """`labs` or `videos`."""
    left: tuple[str, ...]
    """What `deckz status` finds left to publish."""
    outcome: str
    """`published`, `would publish` (`dry_run`), `up to date`, `left` (not \
    asked to publish), `not published` (a push failed before) or `failed`."""
    detail: str = ""

    @property
    def problem(self) -> bool:
        return self.outcome == "failed"


@dataclass(frozen=True)
class PushReport:
    dry_run: bool
    repositories: tuple[RepoPush, ...] = ()
    stopped: str = ""
    """Why the pushes stopped before the end, when they did."""
    publish: tuple[PublishResult, ...] = field(default=())
    publish_asked: bool = False
    """Whether the labs and videos were to be published (`publish`)."""

    @property
    def ok(self) -> bool:
        """Whether every push (and publish) went through, no branch diverged."""
        return not (
            self.stopped
            or any(r.problem for r in self.repositories)
            or any(p.problem for p in self.publish)
        )


def push(
    settings: "GlobalSettings",
    *,
    dry_run: bool = False,
    force: bool = False,
    publish: bool = False,
) -> PushReport:
    """Push deckz, the labs' repositories and the repository, then publish.

    Args:
        settings: The repository's settings.
        dry_run: Fetch, and only report what would be pushed and published.
        force: Force-push (with a lease) the labs' branches a rebase rewrote.
        publish: Publish the labs and the videos once pushed, when something \
            is left to.

    Returns:
        What was pushed, or wasn't and why, then what was published or is left.
    """
    repositories: list[RepoPush] = []
    deckz = deckz_push(settings, dry_run=dry_run)
    if deckz is not None:
        repositories.append(deckz)
        if deckz.problem:
            stopped = (
                f"deckz {_wasnt(dry_run)} pushed, so nothing else "
                f"{'would be' if dry_run else 'was'}: the repository's CI "
                "installs deckz from its remote, and would check the repository "
                "against a deckz lacking what it depends on. Fix deckz's branch "
                "(above), then `deckz push` again"
            )
            return PushReport(
                dry_run, tuple(repositories), stopped, publish_asked=publish
            )
    # Every lab repository is tried, to show all that blocks at once.
    labs = lab_pushes(settings, dry_run=dry_run, force=force)
    repositories.extend(labs)
    if failed := [lab.name for lab in labs if lab.problem]:
        stopped = (
            f"{', '.join(failed)} {_wasnt(dry_run)} pushed, so the repository "
            f"{'would not be' if dry_run else 'was not'} either, nor anything "
            "published: its content links to those repositories' branches. Fix "
            "them (above), then `deckz push` again"
        )
        return PushReport(dry_run, tuple(repositories), stopped, publish_asked=publish)
    own = repository_push(settings, dry_run=dry_run)
    repositories.append(own)
    published = publications(
        settings, dry_run=dry_run, publish=publish, after_problem=own.problem
    )
    return PushReport(
        dry_run, tuple(repositories), "", tuple(published), publish_asked=publish
    )


def _wasnt(dry_run: bool) -> str:
    return "wouldn't be" if dry_run else "wasn't"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
        env=_env(),
    )


def _out(cwd: Path, *args: str) -> str:
    result = _git(cwd, *args)
    return "" if result.returncode else result.stdout.strip()


def _shown(path: Path, git_dir: Path) -> str:
    # `../deckz` for a sibling checkout, the full path for any other.
    shown = relpath(path, git_dir)
    return str(path) if shown.count("..") > 1 else shown


def _fetch(checkout: Path, remote: str, branch: str) -> bool:
    try:
        return not subprocess.run(
            ["git", "-C", str(checkout), "fetch", "--quiet", remote, branch],
            capture_output=True,
            check=False,
            timeout=_FETCH_TIMEOUT,
            env=_env(),
        ).returncode
    except subprocess.TimeoutExpired:
        return False


def _count(checkout: Path, revisions: str) -> int:
    return int(_out(checkout, "rev-list", "--count", revisions) or 0)


def _is_ancestor(checkout: Path, ancestor: str, descendant: str) -> bool:
    return not _git(
        checkout, "merge-base", "--is-ancestor", ancestor, descendant
    ).returncode


def _tracked(checkout: Path, branch: str) -> tuple[str, str, str] | None:
    # The remote, remote branch and remote-tracking ref `branch` tracks.
    found = _out(
        checkout,
        "for-each-ref",
        "--format=%(upstream:remotename)%00%(upstream:remoteref)%00%(upstream)",
        f"refs/heads/{branch}",
    )
    parts = found.split("\0")
    if len(parts) != 3 or not all(parts):
        return None
    remote, ref, tracking = parts
    return remote, ref.removeprefix("refs/heads/"), tracking


def branch_push(
    checkout: Path, branch: str, shown: str, *, dry_run: bool
) -> BranchPush:
    """Push `branch` of `checkout` to the remote branch it tracks, if ahead.

    Never forced: a branch behind its remote is left (a pull brings it up), \
    one diverged from it too, as a problem.

    Args:
        checkout: Any checkout of the repository.
        branch: A local branch.
        shown: How to name the checkout in a fix (`git -C <shown> pull`).
        dry_run: Fetch only.

    Returns:
        What became of it.
    """
    tracked = _tracked(checkout, branch)
    if tracked is None:
        return BranchPush(
            branch,
            "",
            "no_upstream",
            NOT_PUSHED,
            detail=f"tracks no remote branch: `git -C {shown} push -u origin "
            f"{branch}` the first time",
        )
    remote, remote_branch, tracking = tracked
    name = f"{remote}/{remote_branch}"
    fetched = _fetch(checkout, remote, remote_branch)
    as_of = "" if fetched else " (as of the last fetch: fetching failed)"
    local = _out(checkout, "rev-parse", f"refs/heads/{branch}")
    tip = _out(checkout, "rev-parse", "--verify", "--quiet", tracking)
    if tip == local:
        return BranchPush(branch, name, "up_to_date", UP_TO_DATE, detail=as_of.strip())
    if tip and not _is_ancestor(checkout, tip, local):
        behind = _count(checkout, f"{local}..{tip}")
        if _is_ancestor(checkout, local, tip):
            return BranchPush(
                branch,
                name,
                "behind",
                NOT_PUSHED,
                detail=f"{behind} commit(s) behind {name}{as_of}, nothing to "
                f"push: `git -C {shown} pull`",
            )
        ahead = _count(checkout, f"{tip}..{local}")
        return BranchPush(
            branch,
            name,
            "diverged",
            NOT_PUSHED,
            commits=ahead,
            detail=f"diverged from {name}{as_of}: {behind} commit(s) there, "
            f"{ahead} here; never forced: `git -C {shown} pull --rebase`, "
            "then `deckz push` again",
            problem=True,
        )
    commits = _count(checkout, f"{tip}..{local}" if tip else local)
    if dry_run:
        return BranchPush(
            branch,
            name,
            "ahead",
            WOULD_PUSH,
            commits,
            f"{commits} commit(s) to push to {name}{as_of}",
        )
    pushed = subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "push",
            "--quiet",
            remote,
            f"refs/heads/{branch}:refs/heads/{remote_branch}",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=_PUSH_TIMEOUT,
        env=_env(),
    )
    if pushed.returncode:
        stderr = pushed.stderr.strip() or f"git exited {pushed.returncode}"
        return BranchPush(
            branch,
            name,
            "ahead",
            FAILED,
            commits,
            f"push failed: {stderr}\nCheck that `git -C {shown} ls-remote "
            f"{remote}` works (ssh key, network), then `deckz push` again",
            problem=True,
        )
    return BranchPush(
        branch, name, "ahead", PUSHED, commits, f"{commits} commit(s) to {name}"
    )


def deckz_push(settings: "GlobalSettings", *, dry_run: bool) -> RepoPush | None:
    """Push the current branch of the deckz checkout this deckz runs from.

    Returns:
        What became of it; None when deckz doesn't run from a git checkout, \
        or runs from the repository itself.
    """
    from . import setting_up
    from .worktrees import main_checkout

    checkout = setting_up.own_checkout()
    git_dir = settings.paths.git_dir
    if checkout is None or main_checkout(checkout) == main_checkout(git_dir):
        return None
    shown = _shown(checkout, git_dir)
    branch = _out(checkout, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch:
        return RepoPush(
            "deckz",
            "deckz",
            shown,
            skipped=f"{shown} isn't on a branch (a detached HEAD, a rebase): "
            "finish it, then `deckz push` again",
            problem=True,
        )
    pushed = branch_push(checkout, branch, shown, dry_run=dry_run)
    return RepoPush("deckz", "deckz", shown, (pushed,), problem=pushed.problem)


def repository_push(settings: "GlobalSettings", *, dry_run: bool) -> RepoPush:
    """Push the repository's main checkout's branch, from any of its checkouts.

    That branch, not the one checked out here: a worktree's branch \
    (`ws/<name>`) lands on it first (`deckz worktree land`).

    Returns:
        What became of it.
    """
    from .worktrees import main_checkout

    git_dir = settings.paths.git_dir
    main = main_checkout(git_dir)
    shown = _shown(main, git_dir)
    branch = _out(main, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch:
        return RepoPush(
            main.name,
            "repository",
            shown,
            skipped=f"the main checkout {shown} isn't on a branch (a detached "
            "HEAD, a rebase): finish it, then `deckz push` again",
            problem=True,
        )
    pushed = branch_push(main, branch, shown, dry_run=dry_run)
    return RepoPush(main.name, "repository", shown, (pushed,), problem=pushed.problem)


def copierz_command() -> tuple[str, ...] | None:
    """How to run copierz: from deckz's own environment, never the `PATH`.

    Returns:
        The command, or None when copierz isn't installed (deckz's `push` \
        extra).
    """
    if find_spec("copierz") is None:
        return None
    return (sys.executable, "-c", "from copierz.cli import main; main()")


def lab_pushes(
    settings: "GlobalSettings", *, dry_run: bool, force: bool
) -> list[RepoPush]:
    """Push the labs' repositories' branches from their local clones, with copierz.

    Each clone goes to `copierz --root <clone> push <clone> --json`, which \
    fetches, pushes every branch carrying Copier answers that is ahead, and \
    with `force` force-pushes with a lease the branches a rebase rewrote, \
    only when their remote holds nothing they didn't have.

    Returns:
        One per repository, in `labs.repos`' order.
    """
    git_dir = settings.paths.git_dir
    first: dict[str, LabRepoSettings] = {}
    for repo in settings.labs.repos:
        first.setdefault(repo.repo, repo)
    if not first:
        return []
    command = copierz_command()
    if command is None:
        return [
            RepoPush(
                ", ".join(first),
                "lab",
                skipped="copierz, which pushes the labs' repositories, isn't "
                'installed: `pip install "deckz[push]"` (or add `push` to '
                "deckz's extras where the repository declares it), then `deckz "
                "push` again",
            )
        ]
    results = []
    for name, repo in first.items():
        clone = repo.clone_path(git_dir)
        shown = _shown(clone, git_dir)
        if not clone.is_dir():
            results.append(
                RepoPush(
                    name,
                    "lab",
                    skipped=f"no local clone at {shown}, nothing to push: `git "
                    f"clone {repo.fetch_url} {shown}` to work on it, or set its "
                    "`clone` in deckz.yml's `labs.repos`",
                )
            )
            continue
        if (why := _not_a_clone(clone, repo)) is not None:
            results.append(RepoPush(name, "lab", shown, skipped=why))
            continue
        results.append(_copierz_push(command, name, clone, shown, dry_run, force))
    return results


def _not_a_clone(clone: Path, repo: "LabRepoSettings") -> str | None:
    # Why `clone` isn't a clone of `repo`, if it isn't one.
    top = _out(clone, "rev-parse", "--show-toplevel")
    if not top or Path(top).resolve() != clone:
        return (
            f"{clone} isn't the root of a git checkout: set the `clone` of "
            f"{repo.repo} in deckz.yml's `labs.repos`"
        )
    urls = _out(clone, "remote", "-v").split()
    wanted = (repo.repo, f"{repo.repo}.git", repo.fetch_url)
    if not any(url.endswith(w) for url in urls for w in wanted):
        return (
            f"{clone} has no remote at {repo.fetch_url}: it isn't a clone of "
            f"{repo.repo}; set its `clone` in deckz.yml's `labs.repos`"
        )
    return None


def _copierz_push(
    command: tuple[str, ...],
    name: str,
    clone: Path,
    shown: str,
    dry_run: bool,
    force: bool,
) -> RepoPush:
    args = [*command, "--root", str(clone), "push", str(clone), "--json"]
    if force:
        args.append("--force")
    if dry_run:
        args.append("--dry-run")
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        timeout=_PUSH_TIMEOUT,
        env=_env(),
    )
    try:
        branches = json.loads(result.stdout)["branches"]
    except (ValueError, KeyError, TypeError):
        # Its last lines: an error message, or a traceback's end.
        stderr = "\n".join((result.stderr or result.stdout).strip().splitlines()[-5:])
        if result.returncode == 2 and "matches no Copier-generated" in stderr:
            # copierz pushes only the branches carrying Copier answers.
            return RepoPush(
                name,
                "lab",
                shown,
                skipped=f"no branch of {shown} carries Copier answers, which copierz "
                f"pushes: push its branches with `git -C {shown} push`",
            )
        return RepoPush(
            name,
            "lab",
            shown,
            skipped=f"`copierz push` failed (exit {result.returncode}): {stderr}",
            problem=True,
        )
    pushed = tuple(_branch_from_copierz(branch, force=force) for branch in branches)
    return RepoPush(name, "lab", shown, pushed, problem=any(b.problem for b in pushed))


def _branch_from_copierz(found: dict, *, force: bool) -> BranchPush:
    # One branch of `copierz push --json`'s output.
    state = str(found.get("state", ""))
    detail = str(found.get("detail") or "")
    commits = int(found.get("commits") or 0)
    if detail.startswith("pushed"):
        outcome = PUSHED
    elif detail.startswith("would push"):
        outcome = WOULD_PUSH
    elif detail.startswith("push failed"):
        outcome = FAILED
    elif state == "up_to_date":
        outcome = UP_TO_DATE
    else:
        outcome = NOT_PUSHED
    if state == "rewritten" and not force:
        detail = (
            f"{detail.removesuffix(' (pass --force)')}: `deckz push --force` "
            "force-pushes it with a lease, only if its remote holds nothing it "
            "didn't have"
        )
    problem = (
        outcome == FAILED or state == "diverged" or (state == "rewritten" and not force)
    )
    return BranchPush(
        str(found.get("branch", "")),
        str(found.get("remote") or ""),
        state,
        outcome,
        commits if outcome in (PUSHED, WOULD_PUSH) else 0,
        detail,
        problem,
    )


def publications(
    settings: "GlobalSettings", *, dry_run: bool, publish: bool, after_problem: bool
) -> list[PublishResult]:
    """Publish the labs and the videos when something is left to, or say what is.

    Args:
        settings: The repository's settings.
        dry_run: Only say what would be published.
        publish: Publish; else only say what's left to.
        after_problem: The repository's push failed or was refused: publish \
            nothing, a publish takes the upstream branch's files.

    Returns:
        One for the labs and one for the videos, when something is left to \
        publish there.
    """
    from .publishing import publish_labs, publish_videos, videos_preview
    from .status import unpublished

    # Fetched when publishing for real; else as last fetched, like `deckz status`.
    labs, videos = unpublished(settings, fetch=publish and not dry_run)
    results = []
    for what, items in (("labs", labs), ("videos", videos)):
        left = tuple(item.text for item in items)
        if not left:
            continue
        if not publish:
            results.append(
                PublishResult(
                    what,
                    left,
                    "left",
                    f"`deckz push --publish` (or `deckz {what} publish`), once "
                    "reviewed",
                )
            )
            continue
        if dry_run:
            results.append(PublishResult(what, left, "would publish"))
            continue
        if after_problem:
            results.append(
                PublishResult(
                    what,
                    left,
                    "not published",
                    "the repository's push didn't go through, and a publish takes "
                    "its upstream branch's files: fix it, then `deckz push "
                    "--publish` again",
                )
            )
            continue
        try:
            if what == "labs":
                done, _ = publish_labs(settings)
                detail = ""
            else:
                preview = videos_preview(settings)
                done = publish_videos(settings, preview)
                detail = "; ".join(f"warning: {w}" for w in preview.warnings)
        except DeckzError as error:
            results.append(PublishResult(what, left, "failed", str(error)))
            continue
        results.append(
            PublishResult(what, left, "published" if done else "up to date", detail)
        )
    return results
