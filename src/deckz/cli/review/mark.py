from pathlib import Path

from . import app


@app.command()
def mark(
    report: Path,
    paths: list[Path] | None = None,
    /,
    *,
    accept: list[Path] | None = None,
    forget: list[Path] | None = None,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Record files as reviewed, at their working-tree version, in a report.

    Creates REPORT (its front matter only) if it doesn't exist, under
    `review.dir`, then records each of PATHS (directories expand as for
    `deckz review status`) with its git blob sha, and the report's `date`
    (today) and `base` (HEAD). With no PATHS (and no --accept or
    --forget), refreshes every file REPORT records: after reviewing what
    `deckz review diff` shows. Only the front matter's `reviewed` key is
    rewritten.

    A recorded file whose change since its review came from elsewhere
    (commits that reached this branch through the main checkout's branch,
    from another session or person) is refused, and the others marked:
    nobody reviewed those changes. Read them with `deckz review diff REPORT
    PATH`, then mark the file with `--accept PATH`. Exits 1 if a file was
    refused.

    Args:
        report: The report, a Markdown file under `review.dir`
        paths: The files reviewed, from the current directory or the
            repository's root
        accept: Mark this file even though its change came from elsewhere,
            once read (repeat it for several files)
        forget: Remove this file from the report, e.g. deleted or renamed
            (`--forget OLD NEW` records NEW in the same call)
        json: Print one JSON object instead, `{report, created, added,
            refreshed, unchanged, forgotten, not_recorded, refused: [{path,
            reason}]}`
        workdir: Path to move into before running the command

    """
    from ...analyzing.review import locate
    from ...analyzing.review import mark as compute
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    result = compute(
        settings,
        locate(settings, report),
        [locate(settings, p) for p in paths or ()],
        accept=[locate(settings, p) for p in accept or ()],
        forget=[locate(settings, p) for p in forget or ()],
    )
    if json:
        from .._presentation import print_json

        print_json(
            {
                "report": result.report,
                "created": result.created,
                "added": list(result.added),
                "refreshed": list(result.refreshed),
                "unchanged": list(result.unchanged),
                "forgotten": list(result.forgotten),
                "not_recorded": list(result.not_recorded),
                "refused": [
                    {"path": path, "reason": reason} for path, reason in result.refused
                ],
            }
        )
    else:
        if result.created:
            print(f"created {result.report}")
        for label, paths_done in (
            ("added", result.added),
            ("refreshed", result.refreshed),
            ("forgotten", result.forgotten),
        ):
            for path in paths_done:
                print(f"{label}: {path}")
        if result.unchanged:
            count = len(result.unchanged)
            print(
                f"unchanged: {count} file{'s' if count > 1 else ''} already "
                "recorded at their version"
            )
        for path in result.not_recorded:
            print(f"not recorded, nothing to forget: {path}")
        for _, reason in result.refused:
            print(f"refused: {reason}")
    if result.refused:
        from sys import exit as sys_exit

        sys_exit(1)
