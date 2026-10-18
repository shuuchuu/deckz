from pathlib import Path

from . import app
from ._groups import EVERYDAY


@app.command(group=EVERYDAY)
def upload(
    *,
    include_stale: bool = False,
    skip_checks: bool = False,
    dry_run: bool = False,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Upload pdfs to Google Drive.

    Refuses when a PDF doesn't match the deck's content anymore (a fragment
    changed since it was built, or no build produces it), naming them: a
    PDF a narrower build skipped (e.g. presentations after a handout-only
    build) would otherwise go online with old content. Refuses too while
    the content checks report a problem in the deck's files, deferred ones
    included (`deckz check`'s, which let a commit through but not the deck
    going out). Remote files with no local PDF of the same name are deleted
    (unless there's no local PDF at all).

    Args:
        include_stale: Upload the outdated PDFs too
        skip_checks: Don't run the content checks: upload whatever they
            would report
        dry_run: Only list the local PDFs it would upload, the outdated
            ones and the deck's problems, without connecting to Google Drive
        json: With --dry-run, print one JSON object (`pdfs`, `outdated`:
            paths relative to the repository, `problems`: `<check>: <problem>`)
            instead
        workdir: Path to move into before running the command

    Raises:
        DeckzError: When a PDF is outdated, without --include-stale, or the \
            checks report a problem in the deck, without --skip-checks.
    """
    from ..analyzing.affected import deck_findings
    from ..components.factory import GlobalSettingsFactory
    from ..configuring.settings import DeckSettings
    from ..exceptions import DeckzError
    from ..extras import extras_imports
    from ..models import LANGS, lang_dir
    from ..pipelines import deck_targets, outdated_pdfs

    settings = DeckSettings.from_yaml(workdir)
    git_dir = settings.paths.git_dir
    pdfs = {
        lang: sorted(lang_dir(settings.paths.pdf_dir, lang).glob("*.pdf"))
        for lang in LANGS
    }
    langs = [lang for lang in LANGS if pdfs[lang]]
    outdated = (
        outdated_pdfs(deck_targets(settings, langs))
        if dry_run or not include_stale
        else []
    )
    problems = (
        []
        if skip_checks
        else [
            f"{finding.check}: {finding.text}"
            for finding in deck_findings(
                settings, GlobalSettingsFactory(settings).checks_runner().findings()
            )
        ]
    )
    if dry_run:
        found = {
            "pdfs": [
                str(pdf.relative_to(git_dir)) for lang in langs for pdf in pdfs[lang]
            ],
            "outdated": [str(pdf.relative_to(git_dir)) for pdf in outdated],
            "problems": problems,
        }
        if json:
            from ._presentation import print_json

            print_json(found)
            return
        for pdf in found["pdfs"]:
            print(f"{pdf}{' (outdated)' if pdf in found['outdated'] else ''}")
        for problem in problems:
            print(f"problem: {problem}")
        return
    refusals = []
    if outdated and not include_stale:
        names = "\n".join(f"  {pdf.relative_to(git_dir)}" for pdf in outdated)
        refusals.append(
            f"these PDFs don't match the deck's content anymore:\n{names}\n"
            "Rebuild them (`deckz run`, with the kinds and languages they "
            "are), delete them, or pass --include-stale to upload them as "
            "they are"
        )
    if problems:
        listed = "\n".join(f"  {problem}" for problem in problems)
        refusals.append(
            f"the content checks report problems in this deck's files:\n{listed}\n"
            "Fix them (each says how), or pass --skip-checks to upload the deck "
            "as it is"
        )
    if refusals:
        raise DeckzError("\n".join(refusals))

    with extras_imports():
        from ..extras.uploading import Uploader

    Uploader(settings)
