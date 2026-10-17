from pathlib import Path
from typing import TYPE_CHECKING

from .._options import Langs, unique
from . import app

if TYPE_CHECKING:
    from ...analyzing.parity import ParityReport


@app.command(name="parity")
def check_parity(
    deck_dir: Path = Path(),
    slides: list[int] | None = None,
    /,
    *,
    plain: bool = False,
    open: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    json: bool = False,
    worst: int = 15,
    langs: Langs = ("fr",),
) -> None:
    """Compare a built deck's PDF and HTML, slide by slide.

    Needs both built, in every language compared (`deckz run --workdir
    DECK_DIR --handout --no-presentation --no-print --html --lang fr en`):
    this only reads those outputs, it doesn't build anything itself.
    Renders both at 1024x768 into `DECK_DIR/.build/parity/{pdf,html}/NNN.png`
    (`.build/en/parity/` for English), and reports each pair's
    mean absolute grayscale difference, the frames a reveal.js theme shrank
    to fit (a slide element carrying `dataset.ratio`/`dataset.overflow`),
    and anything the page logged, failed to load, or tried to fetch from
    the network (a deck must work offline).

    With no SLIDES given, compares every slide; otherwise only those
    (1-indexed), in every language.

    By default, writes an HTML report per language (`report.html`, next to
    the renders) for a person to open and scan, sortable by gap, shrunk
    frames flagged, and prints a summary, each line prefixed with its
    language. With --plain, prints a section per language instead, the
    worst SLIDES first, and writes contact sheets (`sheet-NN.png`, PDF left
    / HTML right) for an agent to look at.

    Args:
        deck_dir: The deck directory to check, defaulting to the current
            directory
        slides: Only compare these slide numbers, instead of every slide
        plain: Agent-oriented output: a worst-first text report and
            contact sheets, instead of the HTML report
        open: Open the HTML reports once written (ignored with --plain)
        json: Print the findings as a JSON array instead, one object per
            language, each with its "lang" (ignored with --plain)
        worst: How many of the worst slides to report under --plain
        langs: Languages whose builds to compare, English builds being kept
            under `en/` in the build, PDF and HTML directories

    """
    from ...analyzing.parity import compare as compare_parity
    from ...configuring.settings import DeckSettings

    settings = DeckSettings.from_yaml(deck_dir)
    only = set(slides) if slides else None
    reports = [compare_parity(settings, lang, only) for lang in unique(langs)]

    if plain:
        for report in reports:
            _print_plain(report, worst)
        return

    from ._parity_report import write_html_report

    report_paths = [write_html_report(report) for report in reports]

    if json:
        from .._presentation import print_json

        print_json(
            [
                {
                    "lang": report.lang,
                    "pages": report.pages,
                    "slides": report.slides,
                    "mean_diff": report.mean_diff,
                    "diffs": report.diffs,
                    "shrunk": list(report.shrunk),
                    "problems": list(report.problems),
                    "report": str(report_path),
                }
                for report, report_path in zip(reports, report_paths, strict=True)
            ]
        )
    else:
        for report, report_path in zip(reports, report_paths, strict=True):
            lang = report.lang
            if report.mismatched:
                print(
                    f"{lang}: SLIDE COUNT MISMATCH: {report.pages} PDF pages, "
                    f"{report.slides} HTML slides"
                )
            print(
                f"{lang}: {len(report.compared)} slides compared, "
                f"mean diff {report.mean_diff:.2f}"
            )
            print(f"{lang}: Report: {report_path}")

    if open:
        from .._presentation import open_path

        for report_path in report_paths:
            open_path(report_path)


def _print_plain(report: "ParityReport", worst: int) -> None:
    from ...analyzing.parity import write_contact_sheets

    print(f"## {report.lang}")
    print(f"{len(report.compared)} slides compared, mean diff {report.mean_diff:.2f}")
    if report.mismatched:
        print(f"SLIDE COUNT MISMATCH: {report.pages} PDF pages, {report.slides} HTML")
    print(f"Worst {min(worst, len(report.diffs))} (slide: mean abs diff):")
    for i, diff in report.worst(worst):
        print(f"  {i}: {diff:.2f}")
    print(f"HTML frames shrunk to fit ({len(report.shrunk)}):")
    for line in report.shrunk:
        print(f"  {line}")
    print(f"Page problems ({len(report.problems)}):")
    for line in report.problems:
        print(f"  {line}")
    sheets = write_contact_sheets(report)
    print(
        f"Renders and {sheets} contact sheet(s) (PDF left, HTML right) in "
        f"{report.out_dir}"
    )
