from pydantic import ValidationError
from pytest import raises

from deckz.models import (
    DeckDefinition,
    LangMap,
    SectionDefinition,
    is_lang_map,
    resolve_lang,
)


def test_is_lang_map_accepts_fr_en_dict() -> None:
    assert is_lang_map({"fr": "Bonjour", "en": "Hello"})
    assert is_lang_map({"fr": "Bonjour"})


def test_is_lang_map_rejects_plain_string() -> None:
    assert not is_lang_map("Bonjour")


def test_is_lang_map_rejects_unknown_keys() -> None:
    assert not is_lang_map({"fr": "Bonjour", "de": "Hallo"})


def test_is_lang_map_rejects_empty_dict() -> None:
    assert not is_lang_map({})


def test_resolve_lang_plain_string_always_used_as_is() -> None:
    assert resolve_lang("Bonjour", "en") == "Bonjour"
    assert resolve_lang("Bonjour", "fr") == "Bonjour"


def test_resolve_lang_map_picks_requested_lang() -> None:
    value: LangMap = {"fr": "Bonjour", "en": "Hello"}
    assert resolve_lang(value, "en") == "Hello"
    assert resolve_lang(value, "fr") == "Bonjour"


def test_resolve_lang_map_missing_key_raises() -> None:
    value: LangMap = {"fr": "Bonjour"}
    with raises(ValueError, match="missing 'en'"):
        resolve_lang(value, "en")


def test_resolve_lang_map_missing_key_lenient_falls_back() -> None:
    value: LangMap = {"fr": "Bonjour"}
    assert resolve_lang(value, "en", lenient=True) == "Bonjour"


def _deck_data(title: object) -> dict[str, object]:
    return {
        "name": "D",
        "parts": [{"name": "p1", "title": title, "sections": ["hello"]}],
    }


def test_part_title_resolved_from_lang_map_via_context() -> None:
    deck = DeckDefinition.model_validate(
        _deck_data({"fr": "Bonjour", "en": "Hello"}), context={"lang": "en"}
    )
    assert deck.parts[0].title == "Hello"


def test_part_title_defaults_to_fr_without_context() -> None:
    deck = DeckDefinition.model_validate(_deck_data({"fr": "Bonjour", "en": "Hello"}))
    assert deck.parts[0].title == "Bonjour"


def test_part_title_plain_string_always_valid() -> None:
    """A plain string means "the same in every language" -- never a schema error."""
    deck = DeckDefinition.model_validate(_deck_data("Bonjour"), context={"lang": "en"})
    assert deck.parts[0].title == "Bonjour"


def test_part_title_missing_lang_key_raises() -> None:
    with raises(ValidationError, match="missing 'en'"):
        DeckDefinition.model_validate(
            _deck_data({"fr": "Bonjour"}), context={"lang": "en"}
        )


def test_part_title_missing_lang_key_lenient_falls_back() -> None:
    deck = DeckDefinition.model_validate(
        _deck_data({"fr": "Bonjour"}), context={"lang": "en", "lenient": True}
    )
    assert deck.parts[0].title == "Bonjour"


def test_node_include_title_resolved_via_context() -> None:
    """Context must reach titles nested inside `_normalize_include`.

    `_normalize_include` builds `FileInclude`/`SectionInclude` from a raw \
    mapping-form include (`{path: title}`); this only works if it validates \
    that mapping through `model_validate(..., context=...)` rather than \
    constructing the model directly, since pydantic accepts an \
    already-built model instance as-is, without re-running validators.
    """
    data = {
        "name": "D",
        "parts": [
            {
                "name": "p1",
                "sections": [{"hello": {"fr": "Bonjour", "en": "Hello"}}],
            }
        ],
    }
    deck_en = DeckDefinition.model_validate(data, context={"lang": "en"})
    assert deck_en.parts[0].sections[0].title == "Hello"

    deck_fr = DeckDefinition.model_validate(data, context={"lang": "fr"})
    assert deck_fr.parts[0].sections[0].title == "Bonjour"


def test_node_include_bare_string_has_no_title() -> None:
    data = {"name": "D", "parts": [{"name": "p1", "sections": ["hello"]}]}
    deck = DeckDefinition.model_validate(data, context={"lang": "en"})
    assert deck.parts[0].sections[0].title is None


def test_flavor_variables_defaults_to_none() -> None:
    data = {"flavors": [{"name": "f1", "includes": ["hello"]}]}
    definition = SectionDefinition.model_validate(data)
    assert definition.flavors[0].variables is None


def test_flavor_variables_accepts_a_dict() -> None:
    data = {
        "flavors": [
            {"name": "f1", "variables": {"depth": "shallow"}, "includes": ["hello"]}
        ]
    }
    definition = SectionDefinition.model_validate(data)
    assert definition.flavors[0].variables == {"depth": "shallow"}


def test_variables_to_define_defaults_to_empty() -> None:
    definition = SectionDefinition.model_validate(
        {"flavors": [{"name": "f1", "includes": ["hello"]}]}
    )
    assert definition.variables_to_define == []


def test_variables_to_define_bare_string_has_no_allowed_values() -> None:
    data = {
        "variables_to_define": ["depth"],
        "flavors": [{"name": "f1", "includes": ["hello"]}],
    }
    definition = SectionDefinition.model_validate(data)
    (declaration,) = definition.variables_to_define
    assert declaration.name == "depth"
    assert declaration.allowed_values is None


def test_variables_to_define_mapping_form_sets_allowed_values() -> None:
    data = {
        "variables_to_define": [{"depth": ["shallow", "deep"]}],
        "flavors": [{"name": "f1", "includes": ["hello"]}],
    }
    definition = SectionDefinition.model_validate(data)
    (declaration,) = definition.variables_to_define
    assert declaration.name == "depth"
    assert declaration.allowed_values == ["shallow", "deep"]
