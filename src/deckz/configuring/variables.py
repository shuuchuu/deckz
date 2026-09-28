from collections.abc import Mapping
from dataclasses import replace
from functools import reduce
from typing import Any

from ..models import (
    Deck,
    File,
    Lang,
    Node,
    NodeVisitor,
    ResolvedDeck,
    Section,
    is_lang_map,
    resolve_lang,
)
from ..utils import dirs_hierarchy, load_all_yamls
from .settings import GlobalSettings


def get_variables(
    settings: GlobalSettings, lang: Lang = "fr", *, lenient: bool = False
) -> dict[str, Any]:
    merged = reduce(
        lambda a, b: {**a, **b},
        load_all_yamls(
            d
            for p in dirs_hierarchy(
                settings.paths.git_dir,
                settings.paths.user_config_dir,
                settings.paths.current_dir,
            )
            if (d := p / "variables.yml").is_file()
        ),
        {},
    )
    return {
        key: resolve_lang(value, lang, lenient=lenient) if is_lang_map(value) else value
        for key, value in merged.items()
    }


class _VariablesResolverNodeVisitor(NodeVisitor[[Mapping[str, Any]], Node]):
    def visit_file(self, file: File, inherited: Mapping[str, Any]) -> Node:
        return replace(file, variables=inherited)

    def visit_section(self, section: Section, inherited: Mapping[str, Any]) -> Node:
        effective = {**inherited, **section.variables}
        return replace(
            section, nodes=tuple(node.accept(self, effective) for node in section.nodes)
        )


def resolve_variables(deck: Deck, base_variables: Mapping[str, Any]) -> ResolvedDeck:
    """Cascade `base_variables` through `deck`, deepest section wins.

    Every [`File`][deckz.models.File] of the returned deck carries the full \
    dict effective at its position in the tree: `base_variables`, overridden \
    by every enclosing section's own flavor `variables` (set by \
    [`Parser`][deckz.components.parser.Parser]), deepest section wins. \
    `deck` is left untouched.

    Args:
        deck: The deck to resolve, already parsed.
        base_variables: The deck-wide variables (typically `get_variables(...)`).

    Returns:
        The resolved copy of `deck`.
    """
    visitor = _VariablesResolverNodeVisitor()
    base = dict(base_variables)
    return ResolvedDeck(
        replace(
            deck,
            parts={
                name: replace(
                    part, nodes=tuple(node.accept(visitor, base) for node in part.nodes)
                )
                for name, part in deck.parts.items()
            },
        )
    )
