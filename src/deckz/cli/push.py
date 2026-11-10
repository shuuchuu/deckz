from pathlib import Path

from . import app
from ._groups import EVERYDAY


@app.command(group=EVERYDAY)
def push(
    *,
    dry_run: bool = False,
    force: bool = False,
    publish: bool = False,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Push what your work leaves local: deckz, the labs' repositories, then this one.

    In this order, each compared with its remote once fetched:

    1. the deckz checkout this deckz runs from, if any (an editable install,
       e.g. `../deckz`): its current branch, when ahead of the remote branch
       it tracks;
    2. the labs' own repositories (`labs.repos`), from their local clones
       (`labs.repos[].clone`, `../<name>` by default), through copierz:
       every branch carrying Copier answers that is ahead,
       and with --force those a rebase rewrote (stacked branches), with
       `--force-with-lease`, only when their remote holds nothing they
       didn't have; a repository with no local clone is skipped;
    3. this repository: its main checkout's branch (not a worktree's: `deckz
       worktree land` first), when ahead of its upstream.

    deckz comes first because this repository's CI installs deckz from its
    remote, and its content links to the labs' repositories: pushed before
    them, it would be checked against a deckz lacking the code it depends
    on. When deckz's push fails or its branch has diverged, nothing else is
    pushed. And since this repository's content links to the labs'
    repositories' branches, one of them failing (a push failed, a branch
    diverged, a rebased branch left without --force, copierz failed on it)
    stops this repository's push and the publishing, the other labs'
    repositories being pushed all the same, to show all that blocks at once;
    a lab repository only skipped (no local clone, no branch carrying Copier
    answers) doesn't. deckz's and this repository's
    branches are never forced: one behind or diverged from its remote is
    left, with the fix.

    Then, with --publish, publishes the labs and the videos (what `deckz labs
    publish` and `deckz videos publish` do) when `deckz status` finds
    something left to publish; without it, says what's left. Exits 1 if a
    push or a publish failed, or a branch diverged.

    Args:
        dry_run: Fetch, and say what would be pushed and published, without
            pushing nor publishing anything
        force: Force-push (with a lease) the labs' branches a rebase
            rewrote; never deckz's nor this repository's
        publish: Then publish the labs and the videos, if anything is left
            to publish
        json: Print one JSON object instead
        workdir: Path to move into before running the command

    Raises:
        SystemExit: With code 1 if a push or a publish failed, or a branch
            diverged.
    """
    from ..configuring.settings import GlobalSettings
    from ..pushing import push as _push

    report = _push(
        GlobalSettings.from_yaml(workdir),
        dry_run=dry_run,
        force=force,
        publish=publish,
    )
    if json:
        from dataclasses import asdict

        from ._presentation import print_json

        print_json({**asdict(report), "ok": report.ok})
    else:
        from ._presentation import print_push

        print_push(report)
    if not report.ok:
        raise SystemExit(1)
