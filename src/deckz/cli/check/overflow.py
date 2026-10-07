from pathlib import Path

from . import app


@app.command(name="overflow")
def check_overflow(deck_dir: Path = Path(), /, *, json: bool = False) -> None:
    """Report a built handout's shrunk-to-fit frames, worst first.

    Needs the handout already built (`deckz run --workdir DECK_DIR --handout
    --no-presentation --no-print`, or a `deckz run file`/`deckz run section`
    preview, e.g. `.run/section/<section>/<flavor>`): this only reads that
    build's Typst metadata and the PDF's text (poppler's `pdftotext`), it
    doesn't build anything itself.

    For each `overflow_marker_label` Typst metadata marker (see
    `GlobalSettings.overflow_marker_label`), prints its shrink ratio, page,
    frame title and the content file(s) building it (several when the title
    is ambiguous, "?" when none matched). Exits 1 if any frame was shrunk.

    Args:
        deck_dir: The deck (or preview) directory to check, defaulting to
            the current directory
        json: Print the findings as a JSON array instead

    """
    from sys import exit as sys_exit

    from ...analyzing.overflow import shrunk_frames
    from ...configuring.settings import DeckSettings

    settings = DeckSettings.from_yaml(deck_dir)
    frames = shrunk_frames(settings)

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
