"""Report fr content, titles and variables with no English counterpart.

Everything here resolves the deck as deckz would resolve it *without* `--en` \
(i.e. the fr side), then reports what an actual `deckz run --en` would \
currently fail on: a resolved file with no `en/` sibling, or a `{fr, en}` \
translation map that's missing its `en` key. A plain string title/variable is \
always valid (it's used as-is in every language) but is also reported, \
informationally, as `untranslated`, since it commonly means "not yet \
localized" even though it doesn't block a build.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..models import Deck, Section, is_lang_map
from ..utils import dirs_hierarchy, load_yaml
from .sections_search import resolved_files

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings


def _audit_deck(settings: "DeckSettings") -> Deck:
    """Parse a deck fr-only, leniently.

    A coverage check must be able to walk a deck's whole tree precisely to \
    report the translation gaps that would otherwise make a real build fail \
    -- so, unlike an actual `deckz run`/`deckz run --en`, this never raises \
    on an incomplete translation map, it just falls back within the walk.

    Returns:
        The parsed deck.
    """
    from ..components.parser import Parser

    parser = Parser(
        local_latex_dir=settings.paths.local_latex_dir,
        shared_latex_dir=settings.paths.latex_dir,
        file_extensions=settings.file_extensions,
        lang="fr",
        lenient=True,
    )
    return parser.from_deck_definition(settings.paths.deck_definition)


def missing_en_files(settings: "DeckSettings") -> list[tuple[Path, Path]]:
    """Resolved fr files of a deck that have no `en/` sibling on disk.

    Reuses the exact rule `Parser` applies under `--en`, so results are \
    guaranteed consistent with actual build behavior.

    Returns:
        `(fr_path, expected_en_path)` pairs, sorted by `fr_path`.
    """
    deck = _audit_deck(settings)
    missing = []
    for path in sorted(resolved_files(deck)):
        candidate = path.parent / "en" / path.name
        if not candidate.exists():
            missing.append((Path(path), candidate))
    return missing


def _section_yml_paths(deck: Deck) -> set[Path]:
    paths: set[Path] = set()

    def visit(nodes: Iterable[object]) -> None:
        for node in nodes:
            if isinstance(node, Section) and node.parsing_error is None:
                paths.add(node.resolved_path / f"{node.resolved_path.name}.yml")
                visit(node.nodes)

    for part in deck.parts.values():
        visit(part.nodes)
    return paths


def _classify(value: object) -> str | None:
    if is_lang_map(value):
        return None if "en" in value else "missing-en"
    if isinstance(value, str):
        return "untranslated"
    return None


def _deck_title_fields(data: dict[str, Any]) -> Iterable[tuple[str, object]]:
    for part in data.get("parts") or ():
        if not isinstance(part, dict):
            continue
        name = part.get("name")
        if "title" in part:
            yield f"parts[{name}].title", part["title"]
        for item in part.get("sections") or ():
            if isinstance(item, dict) and len(item) == 1:
                key = next(iter(item))
                yield f"parts[{name}].sections[{key}]", item[key]


def _section_title_fields(data: dict[str, Any]) -> Iterable[tuple[str, object]]:
    if "title" in data:
        yield "title", data["title"]
    for key, value in (data.get("default_titles") or {}).items():
        yield f"default_titles[{key}]", value
    for flavor in data.get("flavors") or ():
        if not isinstance(flavor, dict):
            continue
        name = flavor.get("name")
        if "title" in flavor:
            yield f"flavors[{name}].title", flavor["title"]
        for item in flavor.get("includes") or ():
            if isinstance(item, dict) and len(item) == 1:
                key = next(iter(item))
                yield f"flavors[{name}].includes[{key}]", item[key]


def title_gaps(settings: "DeckSettings") -> list[tuple[Path, str, str]]:
    """Titles missing an English counterpart, in a deck's deck.yml and section ymls.

    A title is a gap either because it's a plain string (informational only -- \
    this doesn't block a build, but commonly means "not yet localized"), or \
    because it's a `{fr, en}` map missing its `en` key (this one does block a \
    `deckz run --en`).

    Returns:
        `(yml_path, field_descriptor, status)` triples, `status` one of \
        `"untranslated"` or `"missing-en"`.
    """
    deck_definition_path = settings.paths.deck_definition
    findings: list[tuple[Path, str, str]] = []

    deck_data = load_yaml(deck_definition_path) or {}
    for field, value in _deck_title_fields(deck_data):
        status = _classify(value)
        if status:
            findings.append((deck_definition_path, field, status))

    deck = _audit_deck(settings)
    for yml_path in sorted(_section_yml_paths(deck)):
        data = load_yaml(yml_path) or {}
        for field, value in _section_title_fields(data):
            status = _classify(value)
            if status:
                findings.append((yml_path, field, status))
    return findings


def variable_gaps(settings: "DeckSettings") -> list[tuple[Path, str, str]]:
    """Incomplete `{fr, en}` translation maps declared in a deck's variables.yml.

    Only lang-map-shaped values are inspected: a plain scalar is never held to \
    the translation-completeness rule (deckz has no schema-level way to tell \
    translatable display text from incidental config values here).

    Returns:
        `(variables_yml_path, key, "missing-en")` triples.
    """
    paths = settings.paths
    findings: list[tuple[Path, str, str]] = []
    for p in dirs_hierarchy(paths.git_dir, paths.user_config_dir, paths.current_dir):
        path = p / "variables.yml"
        if not path.is_file():
            continue
        data = load_yaml(path) or {}
        for key, value in data.items():
            if is_lang_map(value) and "en" not in value:
                findings.append((path, key, "missing-en"))
    return findings
