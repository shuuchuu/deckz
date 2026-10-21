from pathlib import Path
from typing import TYPE_CHECKING

from . import app

if TYPE_CHECKING:
    from ...analyzing.i18n_stale import StaleFile

_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


@app.command()
def stale(
    paths: list[Path] | None = None,
    /,
    *,
    plain: bool = False,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Report content files, notebooks and course notes chapters with unported changes.

    Computed from git history alone, no stored markers: a file is stale
    when a commit changed it after the last commit that changed its
    other-language sibling, unless that commit's `Lang-sync` trailer
    (`fr-only (<reason>)`/`en-only (<reason>)`) exempts it. A `Lang-sync:
    pending` commit, or one with no trailer, still counts, until a commit
    changes the sibling or names the file in a `Lang-synced: <path>`
    trailer (`deckz i18n mark-synced`, when nothing needs porting after all).

    Restricts to the pairs with a path under one of PATHS if given, else
    every pair in the repository (shared content, every deck's own
    content, and the configured labs notebooks).

    Args:
        paths: Restrict the report to the files or directories given
        plain: Compact, stable lines for a script or an agent (one per
            stale file and commit), instead of the diff command suggested
            for a human
        json: The findings as JSON, `{"stale": [{path, sibling, since,
            commits: [{sha, subject}]}]}`, for a script or a UI (`since`:
            the sibling's last commit before them, null if none)
        workdir: Path to move into before running the command

    """
    from ...analyzing.i18n_stale import stale_files
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    findings = stale_files(settings, paths or ())

    if json:
        from json import dumps

        print(dumps({"stale": [_as_json(f) for f in findings]}, ensure_ascii=False))
    elif not findings:
        print("Nothing to port.")
    else:
        _print(findings, plain=plain)

    if findings:
        from sys import exit as sys_exit

        sys_exit(1)


def _as_json(finding: "StaleFile") -> dict[str, object]:
    return {
        "path": str(finding.path),
        "sibling": str(finding.sibling),
        "since": finding.since,
        "commits": [{"sha": c.sha, "subject": c.subject} for c in finding.commits],
    }


def _print(findings: "list[StaleFile]", *, plain: bool) -> None:
    for finding in findings:
        if plain:
            for commit in finding.commits:
                print(f"{finding.path}\t{commit.sha}\t{commit.subject}")
            continue
        since = finding.since[:8] if finding.since else "the beginning"
        print(f"#### {finding.path} (since {since})")
        for commit in finding.commits:
            print(f"  {commit.sha[:8]}  {commit.subject}")
        range_start = finding.since or _EMPTY_TREE
        print(f"  git diff {range_start}..HEAD -- {finding.path}")
    if not plain:
        print(
            "\nPort them, or, if nothing needs porting: "
            'deckz i18n mark-synced <path> --reason "<why>"'
        )
