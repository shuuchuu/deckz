from pathlib import Path

from ...models import Lang
from . import app


@app.command()
def frames(
    pdf: Path | None = None,
    /,
    *,
    lang: Lang = "fr",
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Print each page of a built deck PDF with its frame's file, line and title.

    One `page<TAB>file:line<TAB>title` line per frame page; title, outline
    and divider pages, which no content file builds, aren't listed. Reads
    the build (needs the PDF built first), builds nothing.

    Args:
        pdf: A PDF of the WORKDIR's deck (default: its whole handout in
            LANG), e.g. a part's presentation or the print handout
        lang: Language of the default handout
        json: Print a JSON array of {page, title, file, line} instead
        workdir: Path to move into before running the command
    """
    from dataclasses import asdict

    from ...analyzing.frames import frames as _frames
    from ...configuring.settings import DeckSettings
    from ...models import lang_dir
    from ...utils import deck_name_from_dir

    settings = DeckSettings.from_yaml(workdir)
    if pdf is None:
        name = deck_name_from_dir(settings.paths.current_dir)
        pdf = lang_dir(settings.paths.pdf_dir, lang) / f"{name}-handout.pdf"
    found = _frames(settings, pdf)
    if json:
        from .._presentation import print_json

        print_json([asdict(frame) for frame in found])
        return
    for frame in found:
        where = f"{frame.file or '?'}:{frame.line or '?'}"
        print(f"{frame.page}\t{where}\t{frame.title}")
