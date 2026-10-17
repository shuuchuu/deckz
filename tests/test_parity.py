from json import loads
from pathlib import Path

from pygit2 import init_repository
from pytest import CaptureFixture, raises

from deckz.analyzing.parity import (
    _difference,
    _render_pdf,
    _shoot_html,
    compare,
    write_contact_sheets,
)
from deckz.cli import main
from deckz.cli.check._parity_report import write_html_report
from deckz.configuring.settings import DeckPaths, DeckSettings
from deckz.exceptions import DeckzError
from deckz.models import Lang, lang_dir

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


def _build_deck(settings: DeckSettings, lang: Lang = "fr") -> None:
    import typst

    paths = settings.paths
    pdf_dir = lang_dir(paths.pdf_dir, lang)
    pdf_dir.mkdir(parents=True)
    typst_src = paths.current_dir / "main.typ"
    typst_src.write_text(_TWO_PAGE_TYP, encoding="utf8")
    typst.Compiler(str(typst_src)).compile(output=str(pdf_dir / "mydeck-handout.pdf"))
    html_dir = lang_dir(paths.html_dir, lang) / "mydeck-html"
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


def test_compare_reads_and_writes_the_language_s_directories(
    tmp_path: Path,
) -> None:
    settings = _deck_settings(tmp_path)
    _build_deck(settings, "en")
    paths = settings.paths

    report = compare(settings, "en")

    assert report.lang == "en"
    assert report.compared == (1, 2)
    assert report.out_dir == paths.build_dir / "en" / "parity"
    assert (report.pdf_dir / "002.png").is_file()
    assert not (paths.build_dir / "parity").exists()
    with raises(DeckzError, match=r"not built: .*--lang fr`"):
        compare(settings, "fr")


def test_compare_names_the_build_a_missing_language_needs(tmp_path: Path) -> None:
    settings = _deck_settings(tmp_path)
    _build_deck(settings)

    with raises(DeckzError, match=r"pdf/en/mydeck-handout\.pdf.*--html --lang en`"):
        compare(settings, "en")


def test_check_parity_compares_every_language(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    settings = _deck_settings(tmp_path)
    _build_deck(settings, "fr")
    _build_deck(settings, "en")
    deck_dir = str(settings.paths.current_dir)

    main(("check", "parity", deck_dir, "--lang", "fr", "en"))
    lines = capsys.readouterr().out.splitlines()
    main(("check", "parity", deck_dir, "--lang", "fr", "en", "--json"))
    records = loads(capsys.readouterr().out)

    assert [line.split(":")[0] for line in lines] == ["fr", "fr", "en", "en"]
    assert lines[2].startswith("en: 2 slides compared, mean diff ")
    assert [record["lang"] for record in records] == ["fr", "en"]
    assert records[1]["report"] == str(
        settings.paths.build_dir / "en" / "parity" / "report.html"
    )


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
