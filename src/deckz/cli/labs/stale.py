from pathlib import Path
from typing import TYPE_CHECKING

from . import app

if TYPE_CHECKING:
    from ...labs.stale_outputs import StaleDemo


@app.command()
def stale(
    notebooks: list[Path] | None = None,
    /,
    *,
    plain: bool = False,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Report the demos whose code changed after their outputs were written.

    Computed from git history alone: a demo's outputs were written by the
    last commit (or the working tree) changing them, and it's stale when its
    code cells changed since (blank and comment-only lines aside). Rerun it
    and write its outputs back (`deckz labs gpu pass --write-outputs`, or a
    run and `deckz labs outputs`), or, when the change needs no rerun,
    `deckz labs mark-current <notebook> --reason "<why>"`. Exits 1 when a
    demo is listed.

    Args:
        notebooks: Restrict the report to the notebooks, or directories, given
        plain: Compact, stable lines for a script or an agent (one per stale
            demo and commit, `-` for uncommitted changes)
        json: The findings as JSON, `{"stale": [{path, since, uncommitted,
            commits: [{sha, subject}]}]}` (`since`: the commit that wrote
            the outputs, or marked them current)
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...labs.stale_outputs import stale_demos

    settings = GlobalSettings.from_yaml(workdir)
    found = stale_demos(settings, notebooks or ())

    if json:
        from json import dumps

        print(dumps({"stale": [_as_json(demo) for demo in found]}, ensure_ascii=False))
    elif not found:
        print("Every demo's outputs match its code.")
    else:
        _print(found, plain=plain)

    if found:
        from sys import exit as sys_exit

        sys_exit(1)


def _as_json(demo: "StaleDemo") -> dict[str, object]:
    return {
        "path": str(demo.path),
        "since": demo.since,
        "uncommitted": demo.uncommitted,
        "commits": [{"sha": c.sha, "subject": c.subject} for c in demo.commits],
    }


def _print(found: "list[StaleDemo]", *, plain: bool) -> None:
    for demo in found:
        if plain:
            for commit in demo.commits:
                print(f"{demo.path}\t{commit.sha}\t{commit.subject}")
            if demo.uncommitted:
                print(f"{demo.path}\t-\tnot committed yet")
            continue
        print(f"#### {demo.path} (outputs of {demo.since[:8]})")
        for commit in demo.commits:
            print(f"  {commit.sha[:8]}  {commit.subject}")
        if demo.uncommitted:
            print("  (and the working tree)")
    if not plain:
        print(
            "\nRerun them and write their outputs back (`deckz labs gpu pass"
            " --write-outputs`, or `deckz labs outputs`), or, if the change needs no"
            ' rerun: deckz labs mark-current <notebook> --reason "<why>"'
        )
