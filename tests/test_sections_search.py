from pathlib import Path

from pytest import fixture

from deckz.analyzing.sections_search import flavor_names, search_sections


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")


@fixture
def shared_latex_dir(tmp_path: Path) -> Path:
    shared = tmp_path / "shared" / "latex"
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
        shared / "greetings" / "hello.tex",
        "\\begin{frame}{Bonjour}\n  Bonjour !\n\\end{frame}\n"
        "\\begin{frame}[fragile]{Au revoir}\n  Au revoir !\n\\end{frame}\n",
    )
    # No sibling en/en.yml: section structure is never duplicated for
    # English, only translated body files live under en/.
    _write(
        shared / "greetings" / "en" / "hello.tex",
        "\\begin{frame}{Hello}\n  Hello!\n\\end{frame}\n",
    )
    return shared


def test_search_sections_title_match(shared_latex_dir: Path) -> None:
    section_matches, frame_matches = search_sections(shared_latex_dir, ["greetings"])
    assert [m.section for m in section_matches] == ["greetings"]
    assert not frame_matches


def test_search_sections_frame_title_match_case_insensitive(
    shared_latex_dir: Path,
) -> None:
    section_matches, frame_matches = search_sections(shared_latex_dir, ["BONJOUR"])
    assert not section_matches
    assert [m.frame_title for m in frame_matches] == ["Bonjour"]
    assert frame_matches[0].section == "greetings"


def test_search_sections_matches_bracketed_frame_option(
    shared_latex_dir: Path,
) -> None:
    _, frame_matches = search_sections(shared_latex_dir, ["revoir"])
    assert [m.frame_title for m in frame_matches] == ["Au revoir"]


def test_search_sections_does_not_recurse_into_en_sibling(
    shared_latex_dir: Path,
) -> None:
    # "Hello" only exists as an English frame title, in the non-canonical
    # en/hello.tex sibling; frame search only globs the section's own
    # directory (non-recursively), so it must not turn up here.
    section_matches, frame_matches = search_sections(shared_latex_dir, ["hello"])
    assert not section_matches
    assert not frame_matches


def test_search_sections_or_across_keywords(shared_latex_dir: Path) -> None:
    _, frame_matches = search_sections(shared_latex_dir, ["nonexistent", "revoir"])
    assert [m.frame_title for m in frame_matches] == ["Au revoir"]


def test_search_sections_no_match(shared_latex_dir: Path) -> None:
    section_matches, frame_matches = search_sections(shared_latex_dir, ["nonexistent"])
    assert not section_matches
    assert not frame_matches


def test_flavor_names(shared_latex_dir: Path) -> None:
    assert flavor_names(shared_latex_dir / "greetings" / "greetings.yml") == ["fr"]


def test_search_sections_markdown_heading_match(shared_latex_dir: Path) -> None:
    _write(
        shared_latex_dir / "greetings" / "goodbye.md",
        "# Goodbye\n\nSee you soon!\n",
    )
    _, frame_matches = search_sections(shared_latex_dir, ["goodbye"])
    assert [m.frame_title for m in frame_matches] == ["Goodbye"]
    assert frame_matches[0].file.suffix == ".md"
