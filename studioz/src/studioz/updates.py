"""Keeping workspaces current with the upstream branch.

A workspace branched days ago, never updated, publishes what it has (it
happened on 2026-10-23, before deckz published from the upstream branch):
so studioz fetches the upstream branch at startup, every 15 minutes, and
when a workspace's page opens (at most once a minute), without the person
asking. One fetch serves every workspace: the remote-tracking refs are the
repository's, shared by its worktrees. The fetch writes no `FETCH_HEAD`, so
nothing changes in the main checkout but those refs.

After a fetch, a workspace behind the upstream branch with no commits nor
changes of its own is fast-forwarded at once (decided 2026-10-23: nothing of
the person's can be lost), unless a job or an agent turn runs in it; any
other workspace is offered its update (`studioz.sync`). After any update,
the workspace's `deckz setup` runs, as slides' handbook says to after each
pull (its environment synced, `--force` when `package.json` changed, and
whether `../deckz` is behind its upstream), and what it reported is kept,
with what the update brought, in the workspace's
`.run/studioz/update.json` for the page's banner.
"""

import json
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from os import environ
from pathlib import Path
from threading import Lock
from time import monotonic

from .background import changes, git
from .sync import Upstream, conflicts, state
from .workspaces import STATE_DIR

FETCH_EVERY = 15 * 60
"""Seconds between two fetches while studioz runs."""

FETCH_ON_OPEN = 60
"""A workspace's page opening fetches when the last fetch is older than this."""

_RECORD = STATE_DIR / "update.json"
_NETWORK_TIMEOUT = 180


@dataclass(frozen=True)
class SetupProblem:
    name: str
    detail: str


@dataclass(frozen=True)
class Applied:
    """An update of a workspace, and how its `deckz setup` went."""

    at: datetime
    commits: int
    """The upstream branch's commits it brought."""
    automatic: bool
    """A fast-forward studioz made by itself, or the person's update."""
    setup: tuple[SetupProblem, ...] = ()
    """What `deckz setup` reported missing or failed afterwards."""
    setup_running: bool = False
    seen: bool = False
    """Whether the person closed its banner."""


def applied(workspace: Path) -> Applied | None:
    """The workspace's last update, as recorded.

    Returns:
        It, None if none was recorded (or the record can't be read).
    """
    try:
        data = json.loads((workspace / _RECORD).read_text(encoding="utf8"))
        return Applied(
            datetime.fromisoformat(data["at"]),
            int(data["commits"]),
            bool(data["automatic"]),
            tuple(SetupProblem(**problem) for problem in data["setup"]),
            bool(data["setup_running"]),
            bool(data["seen"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _record(workspace: Path, update: Applied) -> None:
    path = workspace / _RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {**asdict(update), "at": update.at.isoformat()}
    temporary = path.with_name(f".{path.name}.part")
    temporary.write_text(json.dumps(data), encoding="utf8")
    temporary.replace(path)


def mark_seen(workspace: Path) -> None:
    if (found := applied(workspace)) is not None:
        _record(workspace, replace(found, seen=True))


def fast_forwardable(workspace: Path, up: Upstream) -> bool:
    """Whether updating the workspace can't touch anything of the person's.

    Returns:
        True when it's behind the upstream branch with no commit of its own, \
        nothing uncommitted (untracked files included) and no rebase under way.
    """
    where = state(workspace, up)
    return (
        where.behind > 0
        and not where.ahead
        and where.conflicts is None
        and not conflicts(workspace)
        and not changes(workspace)
    )


def _setup_problems(workspace: Path, *, force: bool) -> tuple[SetupProblem, ...]:
    # The workspace's `deckz setup`, as `workspaces.create` runs it.
    from deckz.configuring.settings import GlobalSettings
    from deckz.setting_up import Status, setup

    items = setup(GlobalSettings.from_yaml(workspace), force=force)
    return tuple(
        SetupProblem(item.name, item.detail)
        for item in items
        if item.status in (Status.MISSING, Status.FAILED)
    )


def after_update(
    workspace: Path,
    before: str,
    upstream: str,
    *,
    automatic: bool,
    setup: Callable[..., tuple[SetupProblem, ...]] | None = None,
) -> Applied | None:
    """Record an update of the workspace from `before`, then run its `deckz setup`.

    Args:
        workspace: The workspace, now updated.
        before: Its HEAD before the update.
        upstream: The upstream branch's ref, whose commits `before` lacked \
            are those the update brought (a rebase rewrites the workspace's own).
        automatic: Whether studioz fast-forwarded it by itself.
        setup: What runs `deckz setup`, the workspace's own by default.

    Returns:
        The update as recorded once `deckz setup` ran, None if HEAD didn't move.
    """
    after = git(workspace, "rev-parse", "HEAD") or ""
    if not before or after == before:
        return None
    count = git(workspace, "rev-list", "--count", f"{before}..{upstream}")
    commits = int(count or 0)
    changed = (git(workspace, "diff", "--name-only", before, after) or "").split()
    update = Applied(datetime.now(UTC), commits, automatic, setup_running=True)
    _record(workspace, update)
    problems = (setup or _setup_problems)(workspace, force="package.json" in changed)
    done = Applied(update.at, commits, automatic, problems, setup_running=False)
    _record(workspace, done)
    return done


def fast_forward(workspace: Path, up: Upstream) -> Applied | None:
    """Fast-forward the workspace to the upstream branch, then run its setup.

    Returns:
        The update recorded, None if it couldn't be fast-forwarded.
    """
    before = git(workspace, "rev-parse", "HEAD") or ""
    result = subprocess.run(
        ["git", "-C", str(workspace), "merge", "--ff-only", "--quiet", up.tracking],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return None
    return after_update(workspace, before, up.tracking, automatic=True)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=_NETWORK_TIMEOUT,
        # Nothing may wait for a password typed in a terminal nobody sees.
        env={**environ, "GIT_TERMINAL_PROMPT": "0"},
    )


@dataclass
class Fetcher:
    """When the upstream branch was last fetched, and fetching it again."""

    run: Callable[[list[str]], subprocess.CompletedProcess[str]] = _run
    """Runs the fetch (tests replace it)."""
    fetched: datetime | None = None
    """When the last fetch succeeded."""
    error: str | None = None
    """Why the last fetch failed, None if it didn't."""
    _last_try: float = -1e9
    _lock: Lock = field(default_factory=Lock)

    def due(self, every: float) -> bool:
        return monotonic() - self._last_try >= every

    def fetch(self, main: Path, up: Upstream) -> bool:
        """Fetch the upstream branch's remote, once at a time.

        Returns:
            Whether its branch moved.
        """
        if not self._lock.acquire(blocking=False):
            return False
        try:
            self._last_try = monotonic()
            before = git(main, "rev-parse", "--verify", "--quiet", up.tracking)
            try:
                result = self.run(
                    [
                        "git",
                        "-C",
                        str(main),
                        "fetch",
                        "--quiet",
                        "--no-write-fetch-head",
                        up.remote,
                    ]
                )
            except subprocess.TimeoutExpired:
                self.error = f"git fetch {up.remote} : pas fini après 3 min"
                return False
            if result.returncode:
                lines = (result.stderr or result.stdout).strip().splitlines()
                self.error = lines[-1] if lines else f"code {result.returncode}"
                return False
            self.error = None
            self.fetched = datetime.now(UTC)
            return git(main, "rev-parse", "--verify", "--quiet", up.tracking) != before
        finally:
            self._lock.release()


def recent(update: Applied | None, within: timedelta = timedelta(hours=12)) -> bool:
    """Whether the banner still shows `update`.

    Returns:
        True for an update not yet closed, newer than `within`, or whose \
        `deckz setup` runs or reported a problem.
    """
    if update is None or update.seen:
        return False
    return (
        update.setup_running
        or bool(update.setup)
        or datetime.now(UTC) - update.at < within
    )
