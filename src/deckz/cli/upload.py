from pathlib import Path

from . import app


@app.command()
def upload(*, include_stale: bool = False, workdir: Path = Path()) -> None:
    """Upload pdfs to Google Drive.

    Refuses when a PDF doesn't match the deck's content anymore (a fragment
    changed since it was built, or no build produces it), naming them: a
    PDF a narrower build skipped (e.g. presentations after a handout-only
    build) would otherwise go online with old content.

    Args:
        include_stale: Upload the outdated PDFs too
        workdir: Path to move into before running the command

    Raises:
        DeckzError: When a PDF is outdated, without --include-stale.
    """
    from ..configuring.settings import DeckSettings
    from ..exceptions import DeckzError
    from ..extras import extras_imports
    from ..models import LANGS, lang_dir
    from ..pipelines import deck_targets, outdated_pdfs

    settings = DeckSettings.from_yaml(workdir)
    if not include_stale:
        langs = [
            lang
            for lang in LANGS
            if any(lang_dir(settings.paths.pdf_dir, lang).glob("*.pdf"))
        ]
        if outdated := outdated_pdfs(deck_targets(settings, langs)):
            git_dir = settings.paths.git_dir
            names = "\n".join(f"  {pdf.relative_to(git_dir)}" for pdf in outdated)
            msg = (
                f"these PDFs don't match the deck's content anymore:\n{names}\n"
                "Rebuild them (`deckz run`, with the kinds and languages they "
                "are), delete them, or pass --include-stale to upload them as "
                "they are"
            )
            raise DeckzError(msg)

    with extras_imports():
        from ..extras.uploading import Uploader

    Uploader(settings)
