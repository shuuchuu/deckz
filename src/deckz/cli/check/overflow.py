from pathlib import Path
from typing import TYPE_CHECKING

from . import app

if TYPE_CHECKING:
    from ...configuring.settings import DeckSettings


@app.command(name="overflow")
def check_overflow(
    deck_dir: Path = Path(),
    /,
    *,
    tables: bool = False,
    en: bool = False,
    json: bool = False,
) -> None:
    """Report a built handout's shrunk-to-fit frames, worst first.

    Needs the handout already built (`deckz run --workdir DECK_DIR --handout
    --no-presentation --no-print`, or a `deckz run file`/`deckz run section`
    preview, e.g. `.run/section/<section>/<flavor>`): this only reads that
    build's Typst metadata and the PDF's text (poppler's `pdftotext`), it
    doesn't build anything itself. `--en` checks the English build
    (`deckz run --en`), which deckz keeps apart from the French one.

    For each `overflow_marker_label` Typst metadata marker (see
    `GlobalSettings.overflow_marker_label`), prints its shrink ratio, page,
    frame title and the content file(s) building it (several when the title
    is ambiguous, "?" when none matched). Exits 1 if any frame was shrunk.

    With `--tables`, reports the tables instead, from the
    `table_marker_label` markers (see `GlobalSettings.table_marker_label`),
    most wrapped first: each one's wrap (its height over its height with no
    cell wrapped, 100% when none does), page, frame title, source(s), and
    "overflow" when its longest words alone are wider than the frame. Exits 1
    if any table overflows.

    Args:
        deck_dir: The deck (or preview) directory to check, defaulting to
            the current directory
        tables: Report the tables and how much their cells wrap instead
        en: Check the English build instead of the French one
        json: Print the findings as a JSON array instead

    """
    from sys import exit as sys_exit

    from ...configuring.settings import DeckSettings

    settings = DeckSettings.from_yaml(deck_dir)
    if tables:
        _report_tables(settings, en=en, json=json)
        return

    from ...analyzing.overflow import shrunk_frames

    frames = shrunk_frames(settings, en=en)

    if json:
        from .._presentation import print_json

        print_json(
            [
                {
                    "ratio": frame.ratio,
                    "page": frame.page,
                    "title": frame.title,
                    "sources": list(frame.sources),
                }
                for frame in frames
            ]
        )
    elif not frames:
        print("no shrunk frame")
    else:
        for frame in frames:
            sources = ", ".join(frame.sources)
            print(f"{frame.ratio:>7}  p.{frame.page}  {frame.title}  {sources}")

    if frames:
        sys_exit(1)


def _report_tables(settings: "DeckSettings", *, en: bool, json: bool) -> None:
    from sys import exit as sys_exit

    from ...analyzing.overflow import wrapped_tables

    tables = wrapped_tables(settings, en=en)

    if json:
        from .._presentation import print_json

        print_json(
            [
                {
                    "wrap": table.wrap,
                    "overflow": table.overflow,
                    "page": table.page,
                    "title": table.title,
                    "sources": list(table.sources),
                }
                for table in tables
            ]
        )
    elif not tables:
        print("no table")
    else:
        for table in tables:
            sources = ", ".join(table.sources)
            flag = "  overflow" if table.overflow else ""
            print(f"{table.wrap:>7}  p.{table.page}  {table.title}  {sources}{flag}")

    if any(table.overflow for table in tables):
        sys_exit(1)
