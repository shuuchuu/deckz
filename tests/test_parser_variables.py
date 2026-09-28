from pathlib import Path

from pytest import raises

from deckz.components.parser import Parser
from deckz.configuring.variables import resolve_variables
from deckz.exceptions import DeckParsingError, DeckzError
from deckz.models import Deck, File, FlavorName, PartName, Section


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")


def _frame(title: str) -> str:
    return f"# {title}\n\n{title}!\n"


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    """A shared "outer" section with two flavors, each including "inner".

    "inner" is itself a section with two flavors, one of which declares its
    own `variables_to_define`.

    Returns:
        (local_content_dir, shared_content_dir)
    """
    shared = tmp_path / "shared"
    local = tmp_path / "local"
    _write(
        shared / "inner" / "inner.yml",
        "flavors:\n"
        "  - name: plain\n    includes:\n      - body\n"
        "  - name: constrained\n    variables: { depth: deep }\n"
        "    includes:\n      - body\n",
    )
    _write(shared / "inner" / "body.md", _frame("Body"))
    _write(
        shared / "outer" / "outer.yml",
        "flavors:\n"
        "  - name: shallow\n    variables: { depth: shallow }\n"
        "    includes:\n      - $/inner@plain\n"
        "  - name: deep\n    variables: { depth: deep }\n"
        "    includes:\n      - $/inner@plain\n",
    )
    return local, shared


def _body(deck: Deck) -> File:
    # The single file of an "outer" deck, nested under outer > inner.
    (outer,) = deck.parts[PartName("part_name")].nodes
    assert isinstance(outer, Section)
    (inner,) = outer.nodes
    assert isinstance(inner, Section)
    (body,) = inner.nodes
    assert isinstance(body, File)
    return body


def test_flavor_variables_cascade_into_nested_sections(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    parser = Parser(local, shared, (".md",))
    deck = parser.from_section("outer", FlavorName("shallow"))
    resolved = resolve_variables(deck, {"lang": "fr"})

    # Nested section declared no variables of its own: its file gets the
    # outer section's cascaded dict unchanged.
    assert _body(resolved).variables == {"depth": "shallow", "lang": "fr"}


def test_resolving_leaves_the_parsed_deck_untouched(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    parser = Parser(local, shared, (".md",))
    deck = parser.from_section("outer", FlavorName("shallow"))
    resolve_variables(deck, {"lang": "fr"})

    (outer,) = deck.parts[PartName("part_name")].nodes
    assert isinstance(outer, Section)
    # A section only ever holds its own flavor's variables.
    assert outer.variables == {"depth": "shallow"}
    assert _body(deck).variables == {}


def test_sibling_flavors_do_not_leak_into_each_other(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    parser = Parser(local, shared, (".md",))

    shallow = resolve_variables(parser.from_section("outer", FlavorName("shallow")), {})
    deep = resolve_variables(parser.from_section("outer", FlavorName("deep")), {})

    assert _body(shallow).variables["depth"] == "shallow"
    assert _body(deep).variables["depth"] == "deep"


def test_nested_flavor_variables_override_ancestor(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    _write(
        shared / "outer" / "outer.yml",
        "flavors:\n"
        "  - name: shallow\n    variables: { depth: shallow }\n"
        "    includes:\n      - $/inner@constrained\n",
    )
    parser = Parser(local, shared, (".md",))
    deck = resolve_variables(parser.from_section("outer", FlavorName("shallow")), {})

    assert _body(deck).variables["depth"] == "deep"


def test_variables_to_define_missing_is_a_parsing_error(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    _write(
        shared / "strict" / "strict.yml",
        "variables_to_define:\n  - depth\nflavors:\n"
        "  - name: incomplete\n    includes:\n      - body\n",
    )
    _write(shared / "strict" / "body.md", _frame("Body"))

    parser = Parser(local, shared, (".md",))
    with raises(DeckzError):
        parser.from_section("strict", FlavorName("incomplete"))


def test_variables_to_define_satisfied_has_no_parsing_error(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    _write(
        shared / "strict" / "strict.yml",
        "variables_to_define:\n  - depth\nflavors:\n"
        "  - name: complete\n    variables: { depth: deep }\n"
        "    includes:\n      - body\n",
    )
    _write(shared / "strict" / "body.md", _frame("Body"))

    parser = Parser(local, shared, (".md",))
    deck = parser.from_section("strict", FlavorName("complete"))
    (section,) = deck.parts[PartName("part_name")].nodes
    assert isinstance(section, Section)
    assert section.parsing_error is None
    assert section.variables == {"depth": "deep"}


def test_variables_to_define_allowed_values_rejects_out_of_range(
    tmp_path: Path,
) -> None:
    local, shared = _repo(tmp_path)
    _write(
        shared / "strict" / "strict.yml",
        "variables_to_define:\n  - depth: [shallow, deep]\nflavors:\n"
        "  - name: wrong\n    variables: { depth: medium }\n"
        "    includes:\n      - body\n",
    )
    _write(shared / "strict" / "body.md", _frame("Body"))

    parser = Parser(local, shared, (".md",))
    with raises(DeckzError):
        parser.from_section("strict", FlavorName("wrong"))


def test_variables_to_define_allowed_values_accepts_in_range(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    _write(
        shared / "strict" / "strict.yml",
        "variables_to_define:\n  - depth: [shallow, deep]\nflavors:\n"
        "  - name: right\n    variables: { depth: deep }\n"
        "    includes:\n      - body\n",
    )
    _write(shared / "strict" / "body.md", _frame("Body"))

    parser = Parser(local, shared, (".md",))
    deck = parser.from_section("strict", FlavorName("right"))
    (section,) = deck.parts[PartName("part_name")].nodes
    assert section.parsing_error is None


def test_base_variables_are_overridden_by_flavor_variables(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    parser = Parser(local, shared, (".md",))
    deck = parser.from_section("outer", FlavorName("deep"))
    resolved = resolve_variables(deck, {"depth": "medium", "other": "kept"})

    assert _body(resolved).variables == {"depth": "deep", "other": "kept"}


def test_invalid_section_yaml_is_a_parsing_error(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    _write(shared / "broken" / "broken.yml", "flavors: [\n")

    parser = Parser(local, shared, (".md",))
    with raises(DeckParsingError) as excinfo:
        parser.from_section("broken", FlavorName("any"))
    (error,) = excinfo.value.errors
    assert "is not valid YAML" in error
