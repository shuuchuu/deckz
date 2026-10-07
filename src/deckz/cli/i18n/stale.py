from pathlib import Path

from . import app

_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


@app.command()
def stale(
    paths: list[Path] | None = None,
    /,
    *,
    plain: bool = False,
    workdir: Path = Path(),
) -> None:
    """Report content files and notebooks with changes not ported to their sibling.

    Computed from git history alone, no stored markers: a file is stale
    when a commit changed it after the last commit that changed its
    other-language sibling, unless that commit's `Lang-sync` trailer
    (`fr-only (<reason>)`/`en-only (<reason>)`) exempts it. A `Lang-sync:
    pending` commit, or one with no trailer, still counts.

    Restricts to the pairs with a path under one of PATHS if given, else
    every pair in the repository (shared content, every deck's own
    content, and the configured labs notebooks).

    Args:
        paths: Restrict the report to the files or directories given
        plain: Compact, stable lines for a script or an agent (one per
            stale file and commit), instead of the diff command suggested
            for a human
        workdir: Path to move into before running the command

    """
    from ...analyzing.i18n_stale import stale_files
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    findings = stale_files(settings, paths or ())

    if not findings:
        print("Nothing to port.")
        return

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

    from sys import exit as sys_exit

    sys_exit(1)
