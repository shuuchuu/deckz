from pathlib import Path

from pydantic import ValidationError
from pytest import raises

from deckz.components.parser import Parser
from deckz.exceptions import DeckzError
from deckz.models import PartName, Section


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")


def _frame(title: str) -> str:
    return f"\\begin{{frame}}{{{title}}}\n  {title}!\n\\end{{frame}}\n"


_PLAIN_TITLE_DECK = (
    "name: D\nparts:\n  - name: p1\n    title: Plain\n    sections:\n      - about\n"
)


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    """A repo with a shared section and a local deck-local file, both bilingual.

    Returns:
        (local_latex_dir, shared_latex_dir)
    """
    shared = tmp_path / "shared"
    local = tmp_path / "local"
    _write(
        shared / "greeting" / "greeting.yml",
        "title:\n  fr: Salutation\n  en: Greeting\nflavors:\n"
        "  - name: hello\n    includes:\n      - hello\n",
    )
    _write(shared / "greeting" / "hello.tex", _frame("Bonjour"))
    _write(shared / "greeting" / "en" / "hello.tex", _frame("Hello"))
    _write(local / "about.tex", _frame("A propos"))
    _write(local / "en" / "about.tex", _frame("About"))
    return local, shared


def test_fr_is_default_and_matches_pre_lang_behavior(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    parser = Parser(local, shared, (".tex",))
    deck = parser.from_file("about")
    (file_node,) = deck.parts[PartName("part_name")].nodes
    assert file_node.resolved_path == (local / "about.tex").resolve()


def test_en_prefers_sibling_file(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    parser = Parser(local, shared, (".tex",), lang="en")
    deck = parser.from_file("about")
    (file_node,) = deck.parts[PartName("part_name")].nodes
    assert file_node.resolved_path == (local / "en" / "about.tex").resolve()


def test_en_resolves_shared_section_sibling(tmp_path: Path) -> None:
    from deckz.models import FlavorName

    local, shared = _repo(tmp_path)
    parser = Parser(local, shared, (".tex",), lang="en")
    deck = parser.from_section("greeting", FlavorName("hello"))
    (section_node,) = deck.parts[PartName("part_name")].nodes
    assert isinstance(section_node, Section)
    (file_node,) = section_node.nodes
    assert (
        file_node.resolved_path == (shared / "greeting" / "en" / "hello.tex").resolve()
    )


def test_en_missing_sibling_fails_loudly_no_fr_fallback(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    (local / "en" / "about.tex").unlink()

    parser = Parser(local, shared, (".tex",), lang="en")
    with raises(DeckzError):
        parser.from_file("about")


def test_local_overrides_shared_even_under_en(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    # A same-named file exists in both local and shared, each with its own en/
    # sibling: local must still win over shared, exactly as it does for fr.
    _write(shared / "dup.tex", _frame("Shared FR"))
    _write(shared / "en" / "dup.tex", _frame("Shared EN"))
    _write(local / "dup.tex", _frame("Local FR"))
    _write(local / "en" / "dup.tex", _frame("Local EN"))

    parser = Parser(local, shared, (".tex",), lang="en")
    deck = parser.from_file("dup")
    (file_node,) = deck.parts[PartName("part_name")].nodes
    assert file_node.resolved_path == (local / "en" / "dup.tex").resolve()


def test_section_definition_yml_itself_is_never_lang_aware(tmp_path: Path) -> None:
    """The section's own .yml is a single source of truth, never duplicated."""
    from deckz.models import FlavorName

    local, shared = _repo(tmp_path)
    parser = Parser(local, shared, (".tex",), lang="en")
    # No shared/greeting/en/en.yml exists at all -- resolution must still
    # succeed by reading the one canonical greeting.yml.
    assert not (shared / "greeting" / "en" / "en.yml").exists()
    deck = parser.from_section("greeting", FlavorName("hello"))
    (section_node,) = deck.parts[PartName("part_name")].nodes
    assert section_node.parsing_error is None


def test_plain_string_title_always_valid_for_deck(tmp_path: Path) -> None:
    """A plain string title means "the same in every language" -- never an error."""
    local, shared = _repo(tmp_path)
    _write(local.parent / "deck.yml", _PLAIN_TITLE_DECK)
    parser = Parser(local, shared, (".tex",))
    deck = parser.from_deck_definition(local.parent / "deck.yml")
    assert deck.parts[PartName("p1")].title == "Plain"


def test_plain_string_title_always_valid_for_shared_section(tmp_path: Path) -> None:
    from deckz.models import FlavorName

    local, shared = _repo(tmp_path)
    _write(
        shared / "plain" / "plain.yml",
        "title: Plain\nflavors:\n  - name: only\n    includes:\n      - hello\n",
    )
    _write(shared / "plain" / "hello.tex", _frame("Bonjour"))

    parser = Parser(local, shared, (".tex",))
    deck = parser.from_section("plain", FlavorName("only"))
    (section_node,) = deck.parts[PartName("part_name")].nodes
    assert section_node.parsing_error is None


def test_incomplete_lang_map_title_still_fails_loudly(tmp_path: Path) -> None:
    """A translation map that's started but missing "en" is a real gap."""
    local, shared = _repo(tmp_path)
    _write(
        local.parent / "deck.yml",
        "name: D\nparts:\n  - name: p1\n    title:\n      fr: Plain\n"
        "    sections:\n      - about\n",
    )
    parser = Parser(local, shared, (".tex",), lang="en")
    with raises(ValidationError):
        parser.from_deck_definition(local.parent / "deck.yml")


def test_lenient_bypasses_incomplete_lang_map_title(tmp_path: Path) -> None:
    """Used by the i18n coverage check to walk a deck regardless of gaps."""
    local, shared = _repo(tmp_path)
    _write(
        local.parent / "deck.yml",
        "name: D\nparts:\n  - name: p1\n    title:\n      fr: Plain\n"
        "    sections:\n      - about\n",
    )
    parser = Parser(local, shared, (".tex",), lang="en", lenient=True)
    deck = parser.from_deck_definition(local.parent / "deck.yml")
    assert deck.parts[PartName("p1")].title == "Plain"
