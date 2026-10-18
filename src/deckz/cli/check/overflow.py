from pathlib import Path
from typing import TYPE_CHECKING

from .._options import Langs, unique
from . import app

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ...configuring.settings import DeckSettings
    from ...models import Lang


@app.command(name="overflow")
def check_overflow(
    deck_dir: Path = Path(),
    /,
    *,
    tables: bool = False,
    langs: Langs = ("fr",),
    json: bool = False,
) -> None:
    """Report a built handout's shrunk-to-fit frames and wrapped lines, worst first.

    Needs the handout already built (`deckz run --workdir DECK_DIR --handout
    --no-presentation --no-print`, or a `deckz run file`/`deckz run section`
    preview, e.g. `.run/section/<section>/<flavor>`), in every language
    checked: this only reads the Typst metadata markers its compilation
    recorded, it doesn't build anything itself (a build by an older deckz
    is queried, a whole compilation, and matched by title with the PDF's
    text, from poppler's `pdftotext`).

    For each `overflow_marker_label` Typst metadata marker (see
    `GlobalSettings.overflow_marker_label`), prints its language, shrink
    ratio, page, frame title and the content file and line of its `# Title`
    (with an older build, every file a title matches, "?" when none did),
    one language after the other.

    Then, from the `line_marker_label` markers (see
    `GlobalSettings.line_marker_label`), the header and footer lines that
    wrap onto a second line (a long section title in the breadcrumb, over
    the frame title; a long frame title, out of the header; a long deck
    title in the footer, past the page bottom): each one's language, width
    over its room, first page and how many pages show it, which line, its
    text, what to shorten and, for a frame title, its `# Title`'s file and
    line. A handout built by an
    older deckz, which didn't record them, gets a note to build it again.
    Exits 1 if any frame was shrunk or any line wraps.

    With `--tables`, reports the tables instead, from the
    `table_marker_label` markers (see `GlobalSettings.table_marker_label`),
    most wrapped first: each one's language, wrap (its height over its
    height with no cell wrapped, 100% when none does), page, frame title,
    source(s), and "overflow" when its longest words alone are wider than
    the frame. Exits 1 if any table overflows.

    Args:
        deck_dir: The deck (or preview) directory to check, defaulting to
            the current directory
        tables: Report the tables and how much their cells wrap instead
        langs: Languages whose builds to check, English builds being kept
            under `en/` in the build and PDF directories
        json: Print the findings as a JSON array instead, each with its
            "lang" and "kind" ("frame" or "line"; "table" with `--tables`)

    """
    from sys import exit as sys_exit
    from sys import stderr

    from ...configuring.settings import DeckSettings

    settings = DeckSettings.from_yaml(deck_dir)
    langs = unique(langs)
    if tables:
        _report_tables(settings, langs, json=json)
        return

    from ...analyzing.overflow import shrunk_frames, wrapped_lines

    frames = [
        (lang, frame) for lang in langs for frame in shrunk_frames(settings, lang=lang)
    ]
    lines = []
    for lang in langs:
        found = wrapped_lines(settings, lang=lang)
        if found is None:
            print(
                f"{lang}: header and footer lines not checked: the handout was built "
                "by a deckz that didn't record them, build it again",
                file=stderr,
            )
        else:
            lines += [(lang, line) for line in found]

    if json:
        from .._presentation import print_json

        print_json(
            [
                {
                    "lang": lang,
                    "kind": "frame",
                    "ratio": frame.ratio,
                    "page": frame.page,
                    "title": frame.title,
                    "sources": list(frame.sources),
                    "line": frame.line,
                }
                for lang, frame in frames
            ]
            + [
                {
                    "lang": lang,
                    "kind": "line",
                    "ratio": line.ratio,
                    "page": line.pages[0],
                    "pages": list(line.pages),
                    "where": line.line,
                    "text": line.text,
                    "fix": line.fix,
                    "source": line.source,
                }
                for lang, line in lines
            ]
        )
    else:
        if not frames:
            print("no shrunk frame")
        for lang, frame in frames:
            sources = _sources(frame.sources, frame.line)
            print(f"{lang}  {frame.ratio:>7}  p.{frame.page}  {frame.title}  {sources}")
        for lang, line in lines:
            more = f" and {len(line.pages) - 1} more" if len(line.pages) > 1 else ""
            where = f"  {line.source}" if line.source else ""
            print(
                f"{lang}  {line.ratio:>7}  p.{line.pages[0]}{more}  {line.line} "
                f'wraps: "{line.text}": {line.fix}{where}'
            )

    if frames or lines:
        sys_exit(1)


def _sources(sources: tuple[str, ...], line: int | None) -> str:
    return f"{sources[0]}:{line}" if line else ", ".join(sources)


def _report_tables(
    settings: "DeckSettings", langs: "Sequence[Lang]", *, json: bool
) -> None:
    from sys import exit as sys_exit

    from ...analyzing.overflow import wrapped_tables

    tables = [
        (lang, table) for lang in langs for table in wrapped_tables(settings, lang=lang)
    ]

    if json:
        from .._presentation import print_json

        print_json(
            [
                {
                    "lang": lang,
                    "kind": "table",
                    "wrap": table.wrap,
                    "overflow": table.overflow,
                    "page": table.page,
                    "title": table.title,
                    "sources": list(table.sources),
                    "line": table.line,
                }
                for lang, table in tables
            ]
        )
    elif not tables:
        print("no table")
    else:
        for lang, table in tables:
            sources = _sources(table.sources, table.line)
            flag = "  overflow" if table.overflow else ""
            print(
                f"{lang}  {table.wrap:>7}  p.{table.page}  {table.title}  "
                f"{sources}{flag}"
            )

    if any(table.overflow for _, table in tables):
        sys_exit(1)
