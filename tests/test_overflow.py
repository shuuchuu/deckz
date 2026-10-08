from pathlib import Path

from pygit2 import init_repository
from pytest import raises

from deckz.analyzing.overflow import (
    _headings,
    _normalize,
    _page_titles,
    shrunk_frames,
    wrapped_tables,
)
from deckz.configuring.settings import DeckPaths, DeckSettings
from deckz.exceptions import DeckzError

_MAIN_TYP = """\
#set page(paper: "a4", margin: 2cm)
#metadata((ratio: "87%", page: 1)) <formation-overflow>
Part ⋅ Topic \\
Some Title

#include "content/topic-aaaaaaaaaaaaaaaa.typ"
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
        _MAIN_TYP.replace('#include "content/topic-aaaaaaaaaaaaaaaa.typ"\n', ""),
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
        '#include "content/local-aaaaaaaaaaaaaaaa.typ"\n'
        '#include "shared-bbbbbbbbbbbbbbbb.typ"\n'
        '#include "content/missing-cccccccccccccccc.typ"\n',
        encoding="utf8",
    )
    (build_dir / "content" / "local-aaaaaaaaaaaaaaaa.md").write_text(
        "# Local Title\n", encoding="utf8"
    )
    (build_dir / "shared-bbbbbbbbbbbbbbbb.md").write_text(
        "# Shared Title\n", encoding="utf8"
    )
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
    (build_dir / "content" / "topic-aaaaaaaaaaaaaaaa.typ").write_text(
        "Placeholder content.\n", encoding="utf8"
    )
    (build_dir / "content" / "topic-aaaaaaaaaaaaaaaa.md").write_text(
        "# Some Title\n", encoding="utf8"
    )
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

#include "content/topic-aaaaaaaaaaaaaaaa.typ"
"""


def test_wrapped_tables_reports_most_wrapped_first(tmp_path: Path) -> None:
    settings = _deck_settings(tmp_path)
    current_dir = settings.paths.current_dir
    build_dir = current_dir / ".build" / "deck-handout"
    (build_dir / "content").mkdir(parents=True)
    (build_dir / "deck-handout.typ").write_text(_TABLES_TYP, encoding="utf8")
    (build_dir / "content" / "topic-aaaaaaaaaaaaaaaa.typ").write_text(
        "Placeholder content.\n", encoding="utf8"
    )
    (build_dir / "content" / "topic-aaaaaaaaaaaaaaaa.md").write_text(
        "# Some Title\n", encoding="utf8"
    )
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


def test_wrapped_tables_reads_the_english_build_with_en(tmp_path: Path) -> None:
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
    assert [table.wrap for table in wrapped_tables(settings, en=True)] == ["150%"]
