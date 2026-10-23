from pathlib import Path

from . import app


@app.command()
def diff(
    report: Path,
    paths: list[Path] | None = None,
    /,
    *,
    stat: bool = False,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Show what changed in a report's files since their review.

    For each file REPORT records (or each of PATHS) whose working-tree
    version differs from the one reviewed, a unified diff from the version
    reviewed to the working tree; a file gone is reported as deleted. A
    review of the diff alone then lets `deckz review mark` record the file
    again. Exits 0.

    Args:
        report: The report, a Markdown file under `review.dir`
        paths: Only these of its files (directories expand as for `deckz
            review status`)
        stat: One line per file, with the lines added and removed, instead
            of the diffs
        json: Print one JSON object instead, `{"files": [{path, state
            ("stale" or "deleted"), blob (the version reviewed), added,
            removed, diff}]}` (`diff`, `added` and `removed` null when the
            version reviewed isn't in this clone's objects)
        workdir: Path to move into before running the command

    """
    from ...analyzing.review import diff as compute
    from ...analyzing.review import locate
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    found = compute(
        settings, locate(settings, report), [locate(settings, p) for p in paths or ()]
    )
    if json:
        from dataclasses import asdict

        from .._presentation import print_json

        print_json({"files": [asdict(file) for file in found]})
        return
    if not found:
        print("Nothing changed since the review.")
        return
    for file in found:
        if file.state == "deleted":
            print(f"deleted: {file.path} (reviewed at blob {file.blob[:10]})")
        elif file.diff is None:
            print(
                f"{file.path}: the version reviewed (blob {file.blob}) isn't in "
                "this clone: fetch the branch it was reviewed on, or review the "
                "whole file"
            )
        elif stat:
            print(f"{file.path}\t+{file.added}\t-{file.removed}")
        else:
            print(file.diff, end="")
