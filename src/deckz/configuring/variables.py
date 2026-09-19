from functools import reduce
from typing import Any

from ..models import Deck, File, Lang, NodeVisitor, Section, is_lang_map, resolve_lang
from ..utils import dirs_hierarchy, load_all_yamls
from .settings import GlobalSettings


def get_variables(settings: GlobalSettings, lang: Lang = "fr") -> dict[str, Any]:
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
        key: resolve_lang(value, lang) if is_lang_map(value) else value
        for key, value in merged.items()
    }


class _VariablesResolverNodeVisitor(NodeVisitor[[dict[str, Any]], None]):
    def visit_file(self, file: File, inherited: dict[str, Any]) -> None:
        file.variables = inherited

    def visit_section(self, section: Section, inherited: dict[str, Any]) -> None:
        section.variables = {**inherited, **section.variables}
        for node in section.nodes:
            node.accept(self, section.variables)


def resolve_variables(deck: Deck, base_variables: dict[str, Any]) -> None:
    """Cascade `base_variables` through `deck`, deepest section wins.

    Mutates every [`Section`][deckz.models.Section]'s and \
    [`File`][deckz.models.File]'s `variables` attribute in place, merging \
    `base_variables` with each section's own declared `variables` (set by \
    [`Parser`][deckz.components.parser.Parser] from the matched flavor) as \
    the walk descends, so a `File` ends up with the full dict effective at \
    its position in the tree: `base_variables`, overridden by every \
    enclosing section's flavor `variables`, deepest section wins.

    Args:
        deck: The deck to resolve, already parsed.
        base_variables: The deck-wide variables (typically `get_variables(...)`).
    """
    visitor = _VariablesResolverNodeVisitor()
    for part in deck.parts.values():
        for node in part.nodes:
            node.accept(visitor, base_variables)
