import json
from json import loads
from pathlib import Path

from pygit2 import init_repository
from pytest import CaptureFixture, raises

from deckz.analyzing.overflow import (
    _headings,
    _normalize,
    _page_titles,
    shrunk_frames,
    wrapped_lines,
    wrapped_tables,
)
from deckz.cli import main
from deckz.components import marker_records
from deckz.configuring.settings import DeckPaths, DeckSettings
from deckz.exceptions import DeckzError

_MAIN_TYP = """\
#set page(paper: "a4", margin: 2cm)
#metadata((ratio: "87%", page: 1)) <formation-overflow>
Part ⋅ Topic \\
Some Title

#include "content/topic.typ"
#pagebreak()
Divider page, no breadcrumb here
"""


def test_normalize_strips_markdown_markup() -> None:
    assert _normalize("**Bold** and `code` and a trailing group {#sec}") == (
        "Bold and code and a trailing group"
    )


def test_normalize_collapses_escaped_spaces_and_whitespace() -> None:
    assert _normalize("A\\ non-breaking\\ space   and   extra  spaces") == (
        "A non-breaking space and extra spaces"
    )


def test_normalize_turns_markdown_dashes_into_smart_ones() -> None:
    assert _normalize("Atelier --- Exemple, 1--2") == "Atelier \u2014 Exemple, 1\u20132"


def test_page_titles_reads_a_single_level_breadcrumb_frame(tmp_path: Path) -> None:
    import typst

    main_typ = tmp_path / "main.typ"
    main_typ.write_text(
        '#set page(paper: "a4", margin: 2cm)\nSection \\\nSome Title\n'
        "#pagebreak()\nSection \\\nNot a heading\n",
        encoding="utf8",
    )
    pdf = tmp_path / "main.pdf"
    typst.Compiler(str(main_typ)).compile(output=str(pdf))

    # No "⋅" in either breadcrumb: only the page whose second line is a known
    # heading counts as a frame, the other might be a divider.
    assert _page_titles(pdf, {"Some Title"}) == ["Some Title", "", ""]


def test_page_titles_reads_frame_and_divider_pages(tmp_path: Path) -> None:
    import typst

    main_typ = tmp_path / "main.typ"
    # No include needed for this test: drop it to keep the fixture self-contained.
    main_typ.write_text(
        _MAIN_TYP.replace('#include "content/topic.typ"\n', ""),
        encoding="utf8",
    )
    pdf = tmp_path / "main.pdf"
    typst.Compiler(str(main_typ)).compile(output=str(pdf))

    # pdftotext's output ends with a form feed, so splitting on it yields one
    # trailing empty "page" past the real last one -- harmless, nothing ever
    # points a marker at it.
    assert _page_titles(pdf) == ["Some Title", "", ""]


def test_headings_maps_local_and_shared_fragments(tmp_path: Path) -> None:
    current_dir = tmp_path / "deck"
    git_dir = tmp_path
    content_dir = git_dir / "content"
    local_content_dir = current_dir / "content"
    build_dir = current_dir / ".build" / "deck-handout"
    (build_dir / "content").mkdir(parents=True)
    main_typ = build_dir / "deck-handout.typ"
    main_typ.write_text(
        '#include "content/local.typ"\n'
        '#include "shared.typ"\n'
        '#include "content/missing.typ"\n',
        encoding="utf8",
    )
    (build_dir / "content" / "local.md").write_text("# Local Title\n", encoding="utf8")
    (build_dir / "shared.md").write_text("# Shared Title\n", encoding="utf8")
    # No .md for "missing": the deck no longer includes it, must be ignored.

    found = _headings(
        build_dir,
        main_typ,
        current_dir=current_dir,
        local_content_dir=local_content_dir,
        content_dir=content_dir,
        git_dir=git_dir,
    )

    assert found == {
        "Local Title": ["deck/content/local.md"],
        "Shared Title": ["content/shared.md"],
    }


def _deck_settings(tmp_path: Path) -> DeckSettings:
    init_repository(str(tmp_path))
    current_dir = tmp_path / "deck"
    current_dir.mkdir()
    return DeckSettings(paths=DeckPaths(current_dir=current_dir, git_dir=tmp_path))


def test_shrunk_frames_raises_without_a_built_handout(tmp_path: Path) -> None:
    settings = _deck_settings(tmp_path)

    with raises(DeckzError, match="handout"):
        shrunk_frames(settings)


def test_shrunk_frames_reports_ratio_page_title_and_source(tmp_path: Path) -> None:
    settings = _deck_settings(tmp_path)
    current_dir = settings.paths.current_dir
    (current_dir / "deck.yml").write_text("name: Mydeck\n", encoding="utf8")
    build_dir = current_dir / ".build" / "mydeck-handout"
    (build_dir / "content").mkdir(parents=True)
    (build_dir / "mydeck-handout.typ").write_text(_MAIN_TYP, encoding="utf8")
    (build_dir / "content" / "topic.typ").write_text(
        "Placeholder content.\n", encoding="utf8"
    )
    (build_dir / "content" / "topic.md").write_text("# Some Title\n", encoding="utf8")
    pdf_dir = current_dir / "pdf"
    pdf_dir.mkdir()
    import typst

    typst.Compiler(str(build_dir / "mydeck-handout.typ")).compile(
        output=str(pdf_dir / "mydeck-handout.pdf")
    )

    frames = shrunk_frames(settings)

    assert len(frames) == 1
    frame = frames[0]
    assert frame.ratio == "87%"
    assert frame.page == 1
    assert frame.title == "Some Title"
    assert frame.sources == ("deck/content/topic.md",)


def test_shrunk_frames_is_empty_without_markers(tmp_path: Path) -> None:
    settings = _deck_settings(tmp_path)
    current_dir = settings.paths.current_dir
    build_dir = current_dir / ".build" / "deck-handout"
    build_dir.mkdir(parents=True)
    (build_dir / "deck-handout.typ").write_text("Hello\n", encoding="utf8")
    pdf_dir = current_dir / "pdf"
    pdf_dir.mkdir()
    import typst

    typst.Compiler(str(build_dir / "deck-handout.typ")).compile(
        output=str(pdf_dir / "deck-handout.pdf")
    )

    assert shrunk_frames(settings) == []


_TABLES_TYP = """\
#set page(paper: "a4", margin: 2cm)
#metadata((page: 1, wrap: "100%", overflow: false)) <formation-table>
#metadata((page: 1, wrap: "250%", overflow: true)) <formation-table>
Part ⋅ Topic \\
Some Title

#include "content/topic.typ"
"""


def test_wrapped_tables_reports_most_wrapped_first(tmp_path: Path) -> None:
    settings = _deck_settings(tmp_path)
    current_dir = settings.paths.current_dir
    build_dir = current_dir / ".build" / "deck-handout"
    (build_dir / "content").mkdir(parents=True)
    (build_dir / "deck-handout.typ").write_text(_TABLES_TYP, encoding="utf8")
    (build_dir / "content" / "topic.typ").write_text(
        "Placeholder content.\n", encoding="utf8"
    )
    (build_dir / "content" / "topic.md").write_text("# Some Title\n", encoding="utf8")
    pdf_dir = current_dir / "pdf"
    pdf_dir.mkdir()
    import typst

    typst.Compiler(str(build_dir / "deck-handout.typ")).compile(
        output=str(pdf_dir / "deck-handout.pdf")
    )

    tables = wrapped_tables(settings)

    assert [(table.wrap, table.overflow) for table in tables] == [
        ("250%", True),
        ("100%", False),
    ]
    assert tables[0].page == 1
    assert tables[0].title == "Some Title"
    assert tables[0].sources == ("deck/content/topic.md",)


def test_wrapped_tables_reads_the_english_build_in_en(tmp_path: Path) -> None:
    settings = _deck_settings(tmp_path)
    current_dir = settings.paths.current_dir
    build_dir = current_dir / ".build" / "en" / "deck-handout"
    build_dir.mkdir(parents=True)
    (build_dir / "deck-handout.typ").write_text(
        '#metadata((page: 1, wrap: "150%", overflow: false)) <formation-table>\n'
        "Hello\n",
        encoding="utf8",
    )
    pdf_dir = current_dir / "pdf" / "en"
    pdf_dir.mkdir(parents=True)
    import typst

    typst.Compiler(str(build_dir / "deck-handout.typ")).compile(
        output=str(pdf_dir / "deck-handout.pdf")
    )

    with raises(DeckzError, match="handout"):
        wrapped_tables(settings)
    assert [table.wrap for table in wrapped_tables(settings, lang="en")] == ["150%"]


def _fake_handout(build_dir: Path, pdf: Path, wrap: str) -> None:
    import typst

    build_dir.mkdir(parents=True)
    (build_dir / "deck-handout.typ").write_text(
        f'#metadata((page: 1, wrap: "{wrap}", overflow: false)) <formation-table>\n'
        "Hello\n",
        encoding="utf8",
    )
    pdf.parent.mkdir(parents=True, exist_ok=True)
    typst.Compiler(str(build_dir / "deck-handout.typ")).compile(output=str(pdf))


def test_check_overflow_reports_every_lang(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    settings = _deck_settings(tmp_path)
    current_dir = settings.paths.current_dir
    _fake_handout(
        current_dir / ".build" / "deck-handout",
        current_dir / "pdf" / "deck-handout.pdf",
        "120%",
    )
    _fake_handout(
        current_dir / ".build" / "en" / "deck-handout",
        current_dir / "pdf" / "en" / "deck-handout.pdf",
        "150%",
    )

    main(
        (
            "check",
            "overflow",
            str(current_dir),
            "--tables",
            "--lang",
            "fr",
            "en",
            "--json",
        )
    )

    records = loads(capsys.readouterr().out)
    assert [(record["lang"], record["wrap"]) for record in records] == [
        ("fr", "120%"),
        ("en", "150%"),
    ]


def _line_marker(page: int, line: str, text: str, ratio: str) -> str:
    return (
        f'#metadata((page: {page}, line: "{line}", text: "{text}", '
        f'ratio: "{ratio}", fix: "shorten it")) <formation-line>\n'
    )


def _handout_with_lines(settings: DeckSettings, markers: str) -> Path:
    import typst

    current_dir = settings.paths.current_dir
    build_dir = current_dir / ".build" / "deck-handout"
    build_dir.mkdir(parents=True)
    main_typ = build_dir / "deck-handout.typ"
    main_typ.write_text(markers + "Hello\n", encoding="utf8")
    pdf = current_dir / "pdf" / "deck-handout.pdf"
    pdf.parent.mkdir(parents=True)
    typst.Compiler(str(main_typ)).compile(output=str(pdf))
    # A build keeps its PDF next to its main file too: the record's date is
    # compared with that one.
    main_typ.with_suffix(".pdf").write_bytes(pdf.read_bytes())
    return main_typ


def test_wrapped_lines_groups_a_line_s_pages_worst_first(tmp_path: Path) -> None:
    settings = _deck_settings(tmp_path)
    _handout_with_lines(
        settings,
        _line_marker(2, "footer", "Deck", "103%")
        + _line_marker(5, "header breadcrumb", "A ⋅ B", "120%")
        + _line_marker(6, "header breadcrumb", "A ⋅ B", "121%")
        + _line_marker(7, "footer", "Deck", "104%"),
    )

    lines = wrapped_lines(settings)

    assert lines is not None
    assert [(line.line, line.text, line.ratio, line.pages) for line in lines] == [
        ("header breadcrumb", "A ⋅ B", "121%", (5, 6)),
        ("footer", "Deck", "104%", (2, 7)),
    ]
    assert lines[0].fix == "shorten it"


def test_wrapped_lines_reads_the_build_s_record(tmp_path: Path) -> None:
    settings = _deck_settings(tmp_path)
    main_typ = _handout_with_lines(settings, "")
    marker = {
        "page": 3,
        "line": "footer",
        "text": "Deck",
        "ratio": "110%",
        "fix": "shorten it",
    }
    elements = [{"label": "<formation-line>", "value": marker}]
    marker_records.write(main_typ, ("formation-line",), json.dumps(elements))

    lines = wrapped_lines(settings, query=False)

    assert lines is not None
    assert [(line.text, line.pages) for line in lines] == [("Deck", (3,))]


def test_wrapped_lines_is_none_for_a_build_that_did_not_record_them(
    tmp_path: Path,
) -> None:
    settings = _deck_settings(tmp_path)
    main_typ = _handout_with_lines(settings, _line_marker(2, "footer", "Deck", "103%"))
    # An older deckz recorded the other labels only.
    marker_records.write(main_typ, ("formation-overflow",), "[]")

    assert wrapped_lines(settings) is None


def test_check_overflow_reports_wrapped_lines_and_fails(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    settings = _deck_settings(tmp_path)
    _handout_with_lines(
        settings,
        _line_marker(5, "header breadcrumb", "A ⋅ B", "120%")
        + _line_marker(6, "header breadcrumb", "A ⋅ B", "121%"),
    )

    with raises(SystemExit) as exc_info:
        main(("check", "overflow", str(settings.paths.current_dir)))

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "no shrunk frame" in out
    assert 'p.5 and 1 more  header breadcrumb wraps: "A ⋅ B": shorten it' in out

    with raises(SystemExit):
        main(("check", "overflow", str(settings.paths.current_dir), "--json"))

    assert loads(capsys.readouterr().out) == [
        {
            "lang": "fr",
            "kind": "line",
            "ratio": "121%",
            "page": 5,
            "pages": [5, 6],
            "where": "header breadcrumb",
            "text": "A ⋅ B",
            "fix": "shorten it",
            "source": None,
        }
    ]


def test_check_overflow_notes_a_build_that_did_not_record_lines(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    settings = _deck_settings(tmp_path)
    main_typ = _handout_with_lines(settings, "")
    marker_records.write(main_typ, ("formation-overflow",), "[]")

    main(("check", "overflow", str(settings.paths.current_dir)))

    captured = capsys.readouterr()
    assert "no shrunk frame" in captured.out
    assert "build it again" in captured.err
