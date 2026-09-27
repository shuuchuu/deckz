from pathlib import Path

from pytest import fixture

from deckz.analyzing.sections_search import flavor_names, search_sections


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")


@fixture
def shared_content_dir(tmp_path: Path) -> Path:
    shared = tmp_path / "shared" / "content"
    _write(
        shared / "greetings" / "greetings.yml",
        "title: Greetings\n"
        "default_titles:\n"
        "  hello: Salut\n"
        "flavors:\n"
        "  - name: fr\n"
        "    includes:\n"
        "      - hello\n",
    )
    _write(
        shared / "greetings" / "hello.md",
        "# Bonjour\n\nBonjour !\n\n# Au revoir\n\nAu revoir !\n",
    )
    # No sibling en/en.yml: section structure is never duplicated for
    # English, only translated body files live under en/.
    _write(shared / "greetings" / "en" / "hello.md", "# Hello\n\nHello!\n")
    return shared


def test_search_sections_title_match(shared_content_dir: Path) -> None:
    section_matches, frame_matches = search_sections(shared_content_dir, ["greetings"])
    assert [m.section for m in section_matches] == ["greetings"]
    assert not frame_matches


def test_search_sections_frame_title_match_case_insensitive(
    shared_content_dir: Path,
) -> None:
    section_matches, frame_matches = search_sections(shared_content_dir, ["BONJOUR"])
    assert not section_matches
    assert [m.frame_title for m in frame_matches] == ["Bonjour"]
    assert frame_matches[0].section == "greetings"


def test_search_sections_does_not_recurse_into_en_sibling(
    shared_content_dir: Path,
) -> None:
    # "Hello" only exists as an English frame title, in the non-canonical
    # en/hello.md sibling; frame search only globs the section's own
    # directory (non-recursively), so it must not turn up here.
    section_matches, frame_matches = search_sections(shared_content_dir, ["hello"])
    assert not section_matches
    assert not frame_matches


def test_search_sections_or_across_keywords(shared_content_dir: Path) -> None:
    _, frame_matches = search_sections(shared_content_dir, ["nonexistent", "revoir"])
    assert [m.frame_title for m in frame_matches] == ["Au revoir"]


def test_search_sections_no_match(shared_content_dir: Path) -> None:
    section_matches, frame_matches = search_sections(
        shared_content_dir, ["nonexistent"]
    )
    assert not section_matches
    assert not frame_matches


def test_flavor_names(shared_content_dir: Path) -> None:
    assert flavor_names(shared_content_dir / "greetings" / "greetings.yml") == ["fr"]


def test_search_sections_markdown_heading_match(shared_content_dir: Path) -> None:
    _write(
        shared_content_dir / "greetings" / "goodbye.md",
        "# Goodbye\n\nSee you soon!\n",
    )
    _, frame_matches = search_sections(shared_content_dir, ["goodbye"])
    assert [m.frame_title for m in frame_matches] == ["Goodbye"]
    assert frame_matches[0].file.suffix == ".md"


def test_search_sections_en_searches_en_titles_and_files(
    shared_content_dir: Path,
) -> None:
    yml_path = shared_content_dir / "greetings" / "greetings.yml"
    yml_path.write_text(
        yml_path.read_text(encoding="utf8").replace(
            "title: Greetings", "title:\n  fr: Salutations\n  en: Greetings"
        ),
        encoding="utf8",
    )

    section_matches, frame_matches = search_sections(
        shared_content_dir, ["greetings", "hello", "bonjour"], "en"
    )

    assert [m.title for m in section_matches] == ["Greetings"]
    assert [m.frame_title for m in frame_matches] == ["Hello"]
    assert frame_matches[0].file.parent.name == "en"
