"""Compare a built deck's PDF and HTML versions, slide by slide.

Renders `pdf/<name>-handout.pdf`'s pages and screenshots
`html/<name>-html/index.html`'s slides in headless Chromium, both at
`WIDTH`x`HEIGHT`, writing `<deck-dir>/.build/parity/{pdf,html}/NNN.png`
(each slide, numbered from 1, in both renders). Reports, for each pair, its
mean absolute grayscale difference (0-255); the frames a reveal.js theme
shrank to fit, through a documented contract (a shrunk slide element
carries `dataset.ratio` and `dataset.overflow`, same as
`formation.typ`'s `<formation-overflow>` counterpart deckz's own `check
overflow` reads from the PDF); and anything the page logged, failed to
load, or tried to fetch from the network (a deck must work offline).

Videos are shown at their last frame, which is their poster, the PDF's
stand-in. Nothing here modifies a file outside `<deck-dir>/.build/parity/`.
"""

from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree
from typing import TYPE_CHECKING, Any

from ..exceptions import DeckzError
from ..utils import deck_name_from_dir

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings

WIDTH, HEIGHT = 1024, 768
SHEET_PAIRS = 4
THUMB = (512, 384)

# Every video at its last frame (its poster), paused, without the controls
# Chromium overlays on a paused video: a screenshot mid-play would compare a
# random frame with the PDF's poster.
_SETTLE_VIDEOS = """async (index) => {
  const videos = [...Reveal.getSlides()[index].querySelectorAll("video")];
  await Promise.all(videos.map(async (video) => {
    video.pause();
    video.controls = false;
    const once = (event) =>
      new Promise((resolve) => video.addEventListener(event, resolve, { once: true }));
    if (video.readyState < 1) {
      await once("loadedmetadata");
    }
    const seeked = once("seeked");
    video.currentTime = video.duration;
    await seeked;
  }));
}"""


@dataclass(frozen=True)
class ParityReport:
    """The result of comparing one deck's PDF and HTML, slide by slide."""

    out_dir: Path
    """`<deck-dir>/.build/parity`: where every render and report is written."""
    pdf_dir: Path
    html_dir: Path
    pages: int
    """Number of PDF pages."""
    slides: int
    """Number of HTML slides."""
    compared: tuple[int, ...]
    """Slide numbers (1-indexed) present in both renders, in order."""
    diffs: dict[int, float]
    """Each compared slide's mean absolute grayscale difference (0-255)."""
    shrunk: tuple[str, ...]
    """One line per HTML frame shrunk to fit, as reported by the theme."""
    problems: tuple[str, ...]
    """What the HTML page logged, failed to load, or tried to fetch."""

    @property
    def mismatched(self) -> bool:
        """Whether the PDF and HTML don't have the same number of slides."""
        return self.pages != self.slides

    @property
    def mean_diff(self) -> float:
        """The mean difference over every compared slide, or 0 if none were."""
        return sum(self.diffs.values()) / max(len(self.diffs), 1)

    def worst(self, count: int) -> list[tuple[int, float]]:
        """The `count` compared slides with the highest difference, worst first.

        Returns:
            `(slide, diff)` pairs, worst first.
        """
        return sorted(self.diffs.items(), key=lambda item: -item[1])[:count]


def _render_pdf(pdf: Path, out: Path) -> int:
    import pypdfium2

    document = pypdfium2.PdfDocument(pdf)
    for i, page in enumerate(document, 1):
        page.render(scale=WIDTH / page.get_width()).to_pil().save(out / f"{i:03}.png")
    return len(document)


def _launch(playwright: Any) -> Any:
    from playwright.sync_api import Error

    try:
        return playwright.chromium.launch()
    except Error:
        # No browser downloaded for this Playwright version: the system's.
        return playwright.chromium.launch(
            executable_path="/usr/bin/chromium", args=["--no-sandbox"]
        )


def _shoot_html(
    index: Path, out: Path, only: set[int] | None
) -> tuple[int, list[str], list[str]]:
    """Screenshot every slide (or the ones in `only`).

    Returns:
        The slide count, the frames shrunk to fit, and the page's problems.

    Raises:
        DeckzError: If the page never exposed a ready `window.Reveal`.
    """
    from playwright.sync_api import ConsoleMessage, Request, sync_playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    problems: list[str] = []
    with sync_playwright() as playwright:
        browser = _launch(playwright)
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})

        def on_console(message: ConsoleMessage) -> None:
            # Shrunk frames are reported below, by slide number.
            if message.text.startswith("formation: frame"):
                return
            if message.type in {"error", "warning"}:
                problems.append(f"console {message.type}: {message.text}")

        page.on("pageerror", lambda error: problems.append(f"error: {error}"))
        page.on(
            "requestfailed",
            lambda request: problems.append(f"failed to load: {request.url}"),
        )

        def on_request(request: Request) -> None:
            if not request.url.startswith(("file:", "data:", "blob:")):
                problems.append(f"network request: {request.url}")

        page.on("request", on_request)
        page.on("console", on_console)
        page.goto(index.resolve().as_uri())
        try:
            page.wait_for_function("window.Reveal && Reveal.isReady()", timeout=60_000)
        except PlaywrightTimeoutError:
            browser.close()
            msg = "\n".join(["the deck never started:", *problems])
            raise DeckzError(msg) from None
        # The slide menu's button would sit on the frames' footer.
        page.add_style_tag(content=".slide-menu-button { display: none !important; }")
        count = page.evaluate("Reveal.getSlides().length")
        shrunk = page.evaluate(
            """Reveal.getSlides().flatMap((slide, i) => slide.dataset.ratio
              ? [`${i + 1}: shrunk to ${slide.dataset.ratio}`
                 + ` (${slide.dataset.overflow} too tall) `
                 + (slide.querySelector("h4")?.textContent ?? "").trim()]
              : [])"""
        )
        for i in range(count):
            if only is not None and i + 1 not in only:
                continue
            # Slides are numbered flat, but sections are vertical stacks.
            page.evaluate(
                """(i) => {
                  const { h, v } = Reveal.getIndices(Reveal.getSlides()[i]);
                  Reveal.slide(h, v);
                }""",
                i,
            )
            page.evaluate(_SETTLE_VIDEOS, i)
            page.wait_for_timeout(150)
            page.screenshot(path=out / f"{i + 1:03}.png")
        browser.close()
    return count, shrunk, problems


def _difference(a: Path, b: Path) -> float:
    from PIL import Image, ImageChops, ImageStat

    first, second = (
        Image.open(path).convert("L").resize((WIDTH, HEIGHT)) for path in (a, b)
    )
    return ImageStat.Stat(ImageChops.difference(first, second)).mean[0]


def write_contact_sheets(report: ParityReport) -> int:
    """Write contact sheets of PDF (left) / HTML (right) pairs, `SHEET_PAIRS` per sheet.

    Returns:
        How many sheets (`report.out_dir / "sheet-NN.png"`) were written.
    """
    from PIL import Image

    gap = 10
    sheets = 0
    slides = list(report.compared)
    for start in range(0, len(slides), SHEET_PAIRS):
        chunk = slides[start : start + SHEET_PAIRS]
        sheet = Image.new(
            "RGB", (2 * THUMB[0] + gap, len(chunk) * (THUMB[1] + gap)), "gray"
        )
        for row, slide in enumerate(chunk):
            for column, source in enumerate((report.pdf_dir, report.html_dir)):
                thumb = (
                    Image.open(source / f"{slide:03}.png").convert("RGB").resize(THUMB)
                )
                sheet.paste(thumb, (column * (THUMB[0] + gap), row * (THUMB[1] + gap)))
        sheets += 1
        sheet.save(report.out_dir / f"sheet-{sheets:02}.png")
    return sheets


def compare(settings: "DeckSettings", only: set[int] | None = None) -> ParityReport:
    """Build the PDF/HTML comparison of `settings`' deck, slide by slide.

    Needs the deck already built with both `--handout` and `--html`
    (`deckz run --handout --no-presentation --no-print --html`): this only
    reads those outputs, it doesn't build anything itself.

    Args:
        settings: The deck's settings.
        only: Restrict rendering and comparison to these slide numbers \
            (1-indexed), or every slide if `None`.

    Returns:
        The comparison.

    Raises:
        DeckzError: If the deck's PDF and HTML haven't both been built, or \
            if the HTML page never started.
    """
    from ..extras import extras_imports

    with extras_imports("parity"):
        import pypdfium2  # ruff: ignore[unused-import]
        from PIL import Image, ImageChops, ImageStat  # ruff: ignore[unused-import]
        from playwright.sync_api import sync_playwright  # ruff: ignore[unused-import]

    paths = settings.paths
    name = deck_name_from_dir(paths.current_dir)
    pdf_file = paths.pdf_dir / f"{name}-handout.pdf"
    index = paths.html_dir / f"{name}-html" / "index.html"
    missing = [str(path) for path in (pdf_file, index) if not path.is_file()]
    if missing:
        msg = (
            f"not built: {', '.join(missing)} "
            "(`deckz run --handout --no-presentation --no-print --html`)"
        )
        raise DeckzError(msg)

    out = paths.build_dir / "parity"
    rmtree(out, ignore_errors=True)
    pdf_dir, html_dir = out / "pdf", out / "html"
    pdf_dir.mkdir(parents=True)
    html_dir.mkdir()

    pages = _render_pdf(pdf_file, pdf_dir)
    slides, shrunk, problems = _shoot_html(index, html_dir, only)

    compared = tuple(
        i for i in range(1, min(pages, slides) + 1) if only is None or i in only
    )
    diffs = {
        i: _difference(pdf_dir / f"{i:03}.png", html_dir / f"{i:03}.png")
        for i in compared
    }
    return ParityReport(
        out_dir=out,
        pdf_dir=pdf_dir,
        html_dir=html_dir,
        pages=pages,
        slides=slides,
        compared=compared,
        diffs=diffs,
        shrunk=tuple(shrunk),
        problems=tuple(sorted(set(problems))),
    )
