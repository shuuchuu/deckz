from pathlib import Path

from pygit2 import init_repository
from pytest import raises

from deckz.analyzing.parity import (
    _difference,
    _render_pdf,
    _shoot_html,
    compare,
    write_contact_sheets,
)
from deckz.cli.check._parity_report import write_html_report
from deckz.configuring.settings import DeckPaths, DeckSettings
from deckz.exceptions import DeckzError

_TWO_PAGE_TYP = """\
#set page(paper: "a4")
Page one
#pagebreak()
Page two
"""

_FAKE_REVEAL_HTML = """\
<!doctype html>
<meta charset="utf-8">
<div class="reveal"><div class="slides">
  <section class="slide" data-crumbs="A">One</section>
  <section class="slide" data-crumbs="B"><h4>Second</h4>Two</section>
</div></div>
<script>
  console.error("boom");
  const slides = [...document.querySelectorAll('.slide')];
  slides[1].dataset.ratio = "80%";
  slides[1].dataset.overflow = "0.3em";
  window.Reveal = {
    isReady: () => true,
    getSlides: () => slides,
    getIndices: (slide) => ({ h: slides.indexOf(slide), v: 0 }),
    slide: (h, v) => {},
  };
</script>
"""


def _deck_settings(tmp_path: Path) -> DeckSettings:
    init_repository(str(tmp_path))
    current_dir = tmp_path / "deck"
    current_dir.mkdir()
    (current_dir / "deck.yml").write_text("name: Mydeck\n", encoding="utf8")
    return DeckSettings(paths=DeckPaths(current_dir=current_dir, git_dir=tmp_path))


def _build_deck(settings: DeckSettings) -> None:
    import typst

    paths = settings.paths
    paths.pdf_dir.mkdir(parents=True)
    typst_src = paths.current_dir / "main.typ"
    typst_src.write_text(_TWO_PAGE_TYP, encoding="utf8")
    typst.Compiler(str(typst_src)).compile(
        output=str(paths.pdf_dir / "mydeck-handout.pdf")
    )
    html_dir = paths.html_dir / "mydeck-html"
    html_dir.mkdir(parents=True)
    (html_dir / "index.html").write_text(_FAKE_REVEAL_HTML, encoding="utf8")


def test_render_pdf_writes_one_png_per_page(tmp_path: Path) -> None:
    import typst

    pdf = tmp_path / "doc.pdf"
    typst_src = tmp_path / "main.typ"
    typst_src.write_text(_TWO_PAGE_TYP, encoding="utf8")
    typst.Compiler(str(typst_src)).compile(output=str(pdf))
    out = tmp_path / "out"
    out.mkdir()

    pages = _render_pdf(pdf, out)

    assert pages == 2
    assert (out / "001.png").is_file()
    assert (out / "002.png").is_file()


def test_difference_is_zero_for_identical_images(tmp_path: Path) -> None:
    from PIL import Image

    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.new("RGB", (10, 10), (120, 40, 200)).save(a)
    Image.new("RGB", (10, 10), (120, 40, 200)).save(b)

    assert _difference(a, b) < 1e-9


def test_difference_is_positive_for_different_images(tmp_path: Path) -> None:
    from PIL import Image

    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(a)
    Image.new("RGB", (10, 10), (255, 255, 255)).save(b)

    assert _difference(a, b) > 200


def test_shoot_html_reads_slide_count_shrunk_frames_and_problems(
    tmp_path: Path,
) -> None:
    index = tmp_path / "index.html"
    index.write_text(_FAKE_REVEAL_HTML, encoding="utf8")
    out = tmp_path / "out"
    out.mkdir()

    count, shrunk, problems = _shoot_html(index, out, None)

    assert count == 2
    assert shrunk == ["2: shrunk to 80% (0.3em too tall) Second"]
    assert problems == ["console error: boom"]
    assert (out / "001.png").is_file()
    assert (out / "002.png").is_file()


def test_shoot_html_restricts_to_only(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_text(_FAKE_REVEAL_HTML, encoding="utf8")
    out = tmp_path / "out"
    out.mkdir()

    _shoot_html(index, out, {2})

    assert not (out / "001.png").exists()
    assert (out / "002.png").is_file()


def test_compare_raises_without_a_built_deck(tmp_path: Path) -> None:
    settings = _deck_settings(tmp_path)

    with raises(DeckzError, match="not built"):
        compare(settings)


def test_compare_reports_pages_slides_diffs_shrunk_and_problems(
    tmp_path: Path,
) -> None:
    settings = _deck_settings(tmp_path)
    _build_deck(settings)

    report = compare(settings)

    assert report.pages == 2
    assert report.slides == 2
    assert not report.mismatched
    assert report.compared == (1, 2)
    assert set(report.diffs) == {1, 2}
    assert report.shrunk == ("2: shrunk to 80% (0.3em too tall) Second",)
    assert report.problems == ("console error: boom",)
    assert (report.pdf_dir / "001.png").is_file()
    assert (report.html_dir / "001.png").is_file()


def test_write_contact_sheets_writes_one_sheet(tmp_path: Path) -> None:
    settings = _deck_settings(tmp_path)
    _build_deck(settings)
    report = compare(settings)

    sheets = write_contact_sheets(report)

    assert sheets == 1
    assert (report.out_dir / "sheet-01.png").is_file()


def test_write_html_report_lists_slides_and_flags_shrunk(tmp_path: Path) -> None:
    settings = _deck_settings(tmp_path)
    _build_deck(settings)
    report = compare(settings)

    path = write_html_report(report)

    html = path.read_text(encoding="utf8")
    assert path == report.out_dir / "report.html"
    assert "2 slides compared" in html
    assert "shrunk" in html
    assert "console error: boom" in html
    assert 'src="pdf/001.png"' in html
    assert 'src="html/002.png"' in html
