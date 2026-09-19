from pathlib import Path

from pytest import raises

from deckz.components.parser import Parser
from deckz.configuring.variables import resolve_variables
from deckz.exceptions import DeckzError
from deckz.models import File, FlavorName, PartName, Section


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")


def _frame(title: str) -> str:
    return f"\\begin{{frame}}{{{title}}}\n  {title}!\n\\end{{frame}}\n"


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    """A shared "outer" section with two flavors, each including "inner".

    "inner" is itself a section with two flavors, one of which declares its
    own `variables_to_define`.

    Returns:
        (local_latex_dir, shared_latex_dir)
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
    _write(shared / "inner" / "body.tex", _frame("Body"))
    _write(
        shared / "outer" / "outer.yml",
        "flavors:\n"
        "  - name: shallow\n    variables: { depth: shallow }\n"
        "    includes:\n      - $/inner@plain\n"
        "  - name: deep\n    variables: { depth: deep }\n"
        "    includes:\n      - $/inner@plain\n",
    )
    return local, shared


def test_flavor_variables_cascade_into_nested_sections(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    parser = Parser(local, shared, (".tex",))
    deck = parser.from_section("outer", FlavorName("shallow"))
    resolve_variables(deck, {"lang": "fr"})

    (outer,) = deck.parts[PartName("part_name")].nodes
    assert isinstance(outer, Section)
    assert outer.variables == {"depth": "shallow", "lang": "fr"}

    (inner,) = outer.nodes
    assert isinstance(inner, Section)
    (body,) = inner.nodes
    # Nested section declared no variables of its own: it inherits its
    # parent's cascaded dict unchanged.
    assert isinstance(body, File)
    assert body.variables == {"depth": "shallow", "lang": "fr"}


def test_sibling_flavors_do_not_leak_into_each_other(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    parser = Parser(local, shared, (".tex",))

    shallow_deck = parser.from_section("outer", FlavorName("shallow"))
    resolve_variables(shallow_deck, {})
    deep_deck = parser.from_section("outer", FlavorName("deep"))
    resolve_variables(deep_deck, {})

    (shallow_outer,) = shallow_deck.parts[PartName("part_name")].nodes
    (deep_outer,) = deep_deck.parts[PartName("part_name")].nodes
    assert isinstance(shallow_outer, Section)
    assert isinstance(deep_outer, Section)
    assert shallow_outer.variables["depth"] == "shallow"
    assert deep_outer.variables["depth"] == "deep"


def test_nested_flavor_variables_override_ancestor(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    parser = Parser(local, shared, (".tex",))
    deck = parser.from_section("outer", FlavorName("shallow"))
    resolve_variables(deck, {})

    (outer,) = deck.parts[PartName("part_name")].nodes
    assert isinstance(outer, Section)
    (inner,) = outer.nodes
    assert isinstance(inner, Section)
    assert inner.flavor == FlavorName("plain")
    assert inner.variables["depth"] == "shallow"


def test_variables_to_define_missing_is_a_parsing_error(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    _write(
        shared / "strict" / "strict.yml",
        "variables_to_define:\n  - depth\nflavors:\n"
        "  - name: incomplete\n    includes:\n      - body\n",
    )
    _write(shared / "strict" / "body.tex", _frame("Body"))

    parser = Parser(local, shared, (".tex",))
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
    _write(shared / "strict" / "body.tex", _frame("Body"))

    parser = Parser(local, shared, (".tex",))
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
    _write(shared / "strict" / "body.tex", _frame("Body"))

    parser = Parser(local, shared, (".tex",))
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
    _write(shared / "strict" / "body.tex", _frame("Body"))

    parser = Parser(local, shared, (".tex",))
    deck = parser.from_section("strict", FlavorName("right"))
    (section,) = deck.parts[PartName("part_name")].nodes
    assert section.parsing_error is None


def test_base_variables_are_overridden_by_flavor_variables(tmp_path: Path) -> None:
    local, shared = _repo(tmp_path)
    parser = Parser(local, shared, (".tex",))
    deck = parser.from_section("outer", FlavorName("deep"))
    resolve_variables(deck, {"depth": "medium", "other": "kept"})

    (outer,) = deck.parts[PartName("part_name")].nodes
    assert isinstance(outer, Section)
    assert outer.variables == {"depth": "deep", "other": "kept"}
