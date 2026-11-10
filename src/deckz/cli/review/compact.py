from pathlib import Path

from . import app


@app.command()
def compact(
    targets: list[Path],
    /,
    *,
    dry_run: bool = False,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Reduce each done finding of reports to one line: git keeps their text.

    A done finding becomes its id, its scope, a short title (its first
    paragraph, cut at about 70 characters), its outcome word and, in
    parentheses, the commits and days its outcome cites, else what it says
    after its outcome word, shortened: `- **I1** — `a.md`, « Types » :
    `int`… *fait* (66fa0179)`. Open and refused findings (whose reason the
    next review reads), the fiche and the rest of the report stay as they
    are, and the findings read the same (`review-findings`, `deckz review
    findings`). A finding already reduced is left as it is: running it again
    changes nothing. The full text stays in git's history, so commit a
    report before reducing what only its working tree holds.

    Exits 0; 1 if a TARGET is no report.

    Args:
        targets: Reports (Markdown files under `review.dir`), or directories
            under it, standing for the reports under them; from the current
            directory or the repository's root
        dry_run: Only say what would be reduced, and the bytes saved
        json: Print one JSON object instead, `{"reports": [{report, ids,
            before, after}], "before", "after"}`: each report with done
            findings to reduce (`ids`), its size in bytes before and after
        workdir: Path to move into before running the command

    """
    from ...analyzing.findings import compact_reports
    from ...analyzing.review import locate
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    found = compact_reports(
        settings, [locate(settings, target) for target in targets], dry_run=dry_run
    )
    changed = [c for c in found if c.ids]
    before = sum(c.before for c in found)
    after = sum(c.after for c in found)
    if json:
        from .._presentation import print_json

        print_json(
            {
                "reports": [
                    {
                        "report": c.report,
                        "ids": list(c.ids),
                        "before": c.before,
                        "after": c.after,
                    }
                    for c in changed
                ],
                "before": before,
                "after": after,
            }
        )
        return
    verb = "would reduce" if dry_run else "reduced"
    for c in changed:
        print(
            f"{c.report}: {verb} {len(c.ids)} done findings, {c.before} -> "
            f"{c.after} bytes ({', '.join(c.ids)})"
        )
    saved = 100 * (before - after) // before if before else 0
    print(
        f"{len(changed)} of {len(found)} reports, "
        f"{sum(len(c.ids) for c in changed)} findings: {before} -> {after} bytes "
        f"(-{saved} %)" + (", nothing written" if dry_run else "")
    )
