from pathlib import Path

from . import app


@app.command()
def fiche(
    targets: list[Path],
    /,
    *,
    workdir: Path = Path(),
) -> None:
    """Print the fiche of reports: everything before their findings.

    A report's fiche is its text after the front matter and before the
    findings heading (`review.findings.heading`, e.g. `## Constats`): what
    a deck pass, or the next review, reads in place of the content and of
    the findings. Their open findings in full: `deckz review findings
    <report> --text`. Several TARGETS are printed one after another, each
    after a `==> <report> <==` line.

    Args:
        targets: Reports (Markdown files under `review.dir`), or shared
            sections (`content/python/basics`, or `python/basics`), each
            standing for its report under `review.dir`'s `sections/`; from
            the current directory or the repository's root
        workdir: Path to move into before running the command

    """
    from ...analyzing.findings import report_fiche
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    found = [report_fiche(settings, target) for target in targets]
    for index, (report, text) in enumerate(found):
        if len(found) > 1:
            print(f"{'' if index == 0 else chr(10)}==> {report} <==")
        print(text, end="")
