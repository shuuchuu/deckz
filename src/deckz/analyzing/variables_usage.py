"""Static detection of `variables.xxx`/`variables['xxx']` usage gaps.

Walks every shared section's every named flavor (not just the ones some \
deck currently happens to use), with the repository-wide `variables.yml`, \
plus every real deck's own tree, with the deck's own variables, as a real \
build would, and reports:

- a fragment referencing a variable that those variables don't set \
    (`undefined`);
- a fragment that fails to parse with the target repo's own Jinja \
    environment (`unparsable`);
- a flavor or deck that fails to parse at all, reported as a `structural` \
    finding instead of aborting the whole survey.

A shared flavor whose only failures are includes of deck-local files (a \
file some deck's own `content/` has, e.g. a per-deck description) can't be \
resolved on its own, by design: it's skipped, the decks using it cover it.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import TemplateSyntaxError, nodes

from ..exceptions import DeckParsingError, DeckzError
from ..models import Deck, File, FlavorName, Lang, Node, Section
from ..utils import all_deck_settings, shared_section_ids

if TYPE_CHECKING:
    from ..components.protocols import RendererProtocol
    from ..configuring.settings import GlobalSettings


@dataclass
class VariablesReport:
    undefined: list[tuple[Path, str]] = field(default_factory=list)
    """Fragments referencing a `variables.xxx` name nothing sets."""

    unparsable: list[tuple[Path, str]] = field(default_factory=list)
    """Fragments that fail to parse with the target repo's own Jinja environment."""

    structural: list[tuple[str, str]] = field(default_factory=list)
    """`(context, error)` pairs for a flavor/deck that failed to parse at all."""


def _content_suffix(path: Path) -> str:
    # Mirrors components.renderer._content_suffix: a checked-in dependency can
    # be named e.g. "foo.md.j2" directly, not just "foo.md".
    return path.with_suffix("").suffix if path.suffix == ".j2" else path.suffix


def referenced_variable_names(ast: "nodes.Template") -> set[str]:
    r"""Names read off the single injected `variables` context value.

    Deliberately narrower than `jinja2.meta.find_undeclared_variables`, \
    which only sees top-level free names (`variables` itself, `handout`, \
    etc.) -- fragments read variables as an attribute or \
    subscript on `variables` (`\V{variables.depth}`, \
    `\V{variables['depth']}`), which that utility doesn't decompose.

    Returns:
        Every such `depth`-like name found in `ast`.
    """
    names = {
        n.attr
        for n in ast.find_all(nodes.Getattr)
        if isinstance(n.node, nodes.Name) and n.node.name == "variables"
    }
    names |= {
        n.arg.value
        for n in ast.find_all(nodes.Getitem)
        if isinstance(n.node, nodes.Name)
        and n.node.name == "variables"
        and isinstance(n.arg, nodes.Const)
        and isinstance(n.arg.value, str)
    }
    return names


def _check_file(
    path: Path,
    variables: Mapping[str, Any],
    renderer: "RendererProtocol",
    report: VariablesReport,
) -> None:
    try:
        env = renderer.environment_for(_content_suffix(path))
        ast = env.parse(path.read_text(encoding="utf8"))
    except TemplateSyntaxError as e:
        report.unparsable.append((path, str(e)))
        return
    report.undefined.extend(
        (path, name)
        for name in sorted(referenced_variable_names(ast))
        if name not in variables
    )


def _files(nodes: Iterable[Node]) -> Iterator[Path]:
    for node in nodes:
        if isinstance(node, Section):
            if node.parsing_error is None and node.resolved_path is not None:
                yield from _files(node.nodes)
        elif isinstance(node, File) and node.resolved_path is not None:
            yield node.resolved_path


def _walk_deck(
    deck: Deck,
    variables: Mapping[str, Any],
    renderer: "RendererProtocol",
    report: VariablesReport,
) -> None:
    for part in deck.parts.values():
        for path in _files(part.nodes):
            _check_file(path, variables, renderer, report)


def _failed_nodes(nodes: Iterable[Node]) -> Iterator[Node]:
    for node in nodes:
        if node.parsing_error is not None:
            yield node
        if isinstance(node, Section):
            yield from _failed_nodes(node.nodes)


def _only_deck_local_gaps(
    deck: Deck, local_content_dirs: list[Path], file_extensions: tuple[str, ...]
) -> bool:
    """Whether every failure of a shared flavor is a file only decks have.

    Returns:
        True if each failed node is a file that's missing from the shared \
        content but present in some deck's local content directory.
    """
    failed = [
        node for part in deck.parts.values() for node in _failed_nodes(part.nodes)
    ]
    return all(
        isinstance(node, File)
        and node.resolved_path is None
        and any(
            (content_dir / node.unresolved_path.with_suffix(extension)).is_file()
            for content_dir in local_content_dirs
            for extension in file_extensions
        )
        for node in failed
    )


def _shared_flavor_contexts(
    settings: "GlobalSettings",
) -> list[tuple[str, FlavorName, str]]:
    from .sections_search import flavor_names

    shared_content_dir = settings.paths.content_dir
    contexts: list[tuple[str, FlavorName, str]] = []
    for section_id in shared_section_ids(shared_content_dir):
        yml_path = shared_content_dir / section_id / f"{Path(section_id).name}.yml"
        for flavor in flavor_names(yml_path):
            contexts.append((section_id, flavor, f"shared:{section_id}@{flavor}"))
    return contexts


def check_variables(settings: "GlobalSettings", lang: Lang = "fr") -> VariablesReport:
    """Survey every shared flavor and every real deck for variable usage gaps.

    Args:
        settings: Repository-wide settings (as built by `GlobalSettings.from_yaml`).
        lang: Language to resolve titles/variables in.

    Returns:
        The findings collected across the whole survey.
    """
    from ..checking import check_scratch_dir
    from ..components.factory import DeckSettingsFactory, GlobalSettingsFactory
    from ..configuring.settings import DeckSettings
    from ..configuring.variables import get_variables

    report = VariablesReport()
    renderer = GlobalSettingsFactory(settings).renderer()
    git_dir = settings.paths.git_dir

    all_decks = list(all_deck_settings(git_dir))
    local_content_dirs = [d.paths.local_content_dir for d in all_decks]
    scratch_settings = DeckSettings.from_yaml(check_scratch_dir(git_dir, "variables"))
    shared_base_variables = {**get_variables(scratch_settings, lang), "lang": lang}
    shared_parser = GlobalSettingsFactory(settings).shared_parser(lang, lenient=True)
    for section_id, flavor, context in _shared_flavor_contexts(settings):
        try:
            deck = shared_parser.from_section(section_id, flavor)
        except DeckParsingError as e:
            if not _only_deck_local_gaps(
                e.deck, local_content_dirs, settings.file_extensions
            ):
                report.structural.append((context, str(e)))
            continue
        except DeckzError as e:
            report.structural.append((context, str(e)))
            continue
        _walk_deck(deck, shared_base_variables, renderer, report)

    for deck_settings in all_decks:
        deck_context = str(
            deck_settings.paths.deck_definition.parent.relative_to(git_dir)
        )
        deck_parser = DeckSettingsFactory(
            deck_settings, lang=lang, lenient=True
        ).parser()
        try:
            deck = deck_parser.from_deck_definition(deck_settings.paths.deck_definition)
        except DeckzError as e:
            report.structural.append((deck_context, str(e)))
            continue
        deck_base_variables = {**get_variables(deck_settings, lang), "lang": lang}
        _walk_deck(deck, deck_base_variables, renderer, report)

    return report
