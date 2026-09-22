"""Static detection of `variables.xxx`/`variables['xxx']` usage gaps.

Walks every shared section's every named flavor (not just the ones some \
deck currently happens to use) plus every real deck's own tree, resolving \
`variables` the same way a real build would (see \
[`resolve_variables`][deckz.configuring.variables.resolve_variables]), and \
reports:

- a fragment referencing a variable that isn't in its resolved `variables` \
    at that point in the tree (`undefined`);
- a section declaring a `variables_to_define` name that no fragment \
    reachable under it, in any flavor, ever reads (`unused`);
- a fragment that fails to parse with the target repo's own Jinja \
    environment (`unparsable`);
- a flavor that fails to parse at all -- typically a `variables_to_define` \
    contract violation raised by `Parser` -- reported as a `structural` \
    finding instead of aborting the whole survey.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import TemplateSyntaxError, nodes

from ..exceptions import DeckzError
from ..models import Deck, File, FlavorName, Lang, Node, Section, SectionDefinition
from ..utils import all_deck_settings, load_yaml, shared_section_ids

if TYPE_CHECKING:
    from ..components.protocols import RendererProtocol
    from ..configuring.settings import GlobalSettings


@dataclass
class VariablesReport:
    undefined: list[tuple[Path, str]] = field(default_factory=list)
    """Fragments referencing a `variables.xxx` name not resolved at that point."""

    unused: list[tuple[Path, str]] = field(default_factory=list)
    """Section ymls declaring a `variables_to_define` name nothing ever reads."""

    unparsable: list[tuple[Path, str]] = field(default_factory=list)
    """Fragments that fail to parse with the target repo's own Jinja environment."""

    structural: list[tuple[str, str]] = field(default_factory=list)
    """`(context, error)` pairs for a flavor/deck that failed to parse at all."""


@dataclass
class _Accumulator:
    declared: dict[Path, set[str]] = field(default_factory=dict)
    referenced: dict[Path, set[str]] = field(default_factory=dict)
    report: VariablesReport = field(default_factory=VariablesReport)


def _content_suffix(path: Path) -> str:
    # Mirrors components.renderer._content_suffix: a checked-in dependency can
    # be named e.g. "foo.tex.j2" directly, not just "foo.tex".
    return path.with_suffix("").suffix if path.suffix == ".j2" else path.suffix


def referenced_variable_names(ast: "nodes.Template") -> set[str]:
    r"""Names read off the single injected `variables` context value.

    Deliberately narrower than `jinja2.meta.find_undeclared_variables`, \
    which only sees top-level free names (`variables` itself, `handout`, \
    etc.) -- fragments read declared/flavor variables as an attribute or \
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


def _section_yml_path(section: Section) -> Path:
    return section.resolved_path / f"{section.resolved_path.name}.yml"


def _declared_names(acc: _Accumulator, section: Section) -> set[str]:
    yml_path = _section_yml_path(section)
    if yml_path not in acc.declared:
        try:
            definition = SectionDefinition.model_validate(load_yaml(yml_path))
            declared = {d.name for d in definition.variables_to_define}
        except Exception:
            declared = set()
        acc.declared[yml_path] = declared
        acc.referenced.setdefault(yml_path, set())
    return acc.declared[yml_path]


def _check_file(
    file: File,
    ancestors: list[tuple[Path, set[str]]],
    renderer: "RendererProtocol",
    acc: _Accumulator,
) -> None:
    if file.parsing_error is not None:
        return
    try:
        env = renderer.environment_for(_content_suffix(file.resolved_path))
        ast = env.parse(file.resolved_path.read_text(encoding="utf8"))
    except TemplateSyntaxError as e:
        acc.report.unparsable.append((file.resolved_path, str(e)))
        return
    for name in referenced_variable_names(ast):
        if name not in file.variables:
            acc.report.undefined.append((file.resolved_path, name))
        for yml_path, declared in ancestors:
            if name in declared:
                acc.referenced[yml_path].add(name)


def _walk_node(
    node: Node,
    ancestors: list[tuple[Path, set[str]]],
    renderer: "RendererProtocol",
    acc: _Accumulator,
) -> None:
    if isinstance(node, Section):
        if node.parsing_error is not None:
            return
        declared = _declared_names(acc, node)
        new_ancestors = (
            [*ancestors, (_section_yml_path(node), declared)] if declared else ancestors
        )
        for child in node.nodes:
            _walk_node(child, new_ancestors, renderer, acc)
    elif isinstance(node, File):
        _check_file(node, ancestors, renderer, acc)


def _walk_deck(
    deck: Deck,
    base_variables: dict[str, Any],
    renderer: "RendererProtocol",
    acc: _Accumulator,
) -> None:
    from ..configuring.variables import resolve_variables

    resolve_variables(deck, base_variables)
    for part in deck.parts.values():
        for node in part.nodes:
            _walk_node(node, [], renderer, acc)


def _shared_flavor_contexts(
    settings: "GlobalSettings",
) -> list[tuple[str, FlavorName, str]]:
    from .sections_search import flavor_names

    shared_latex_dir = settings.paths.latex_dir
    contexts: list[tuple[str, FlavorName, str]] = []
    for section_id in shared_section_ids(shared_latex_dir):
        yml_path = shared_latex_dir / section_id / f"{Path(section_id).name}.yml"
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
    from ..components.factory import GlobalSettingsFactory
    from ..components.parser import Parser
    from ..configuring.settings import DeckSettings
    from ..configuring.variables import get_variables

    acc = _Accumulator()
    renderer = GlobalSettingsFactory(settings).renderer()
    git_dir = settings.paths.git_dir
    shared_latex_dir = settings.paths.latex_dir

    scratch_settings = DeckSettings.from_yaml(check_scratch_dir(git_dir, "variables"))
    shared_base_variables = {**get_variables(scratch_settings, lang), "lang": lang}
    shared_parser = Parser(
        local_latex_dir=shared_latex_dir,
        shared_latex_dir=shared_latex_dir,
        file_extensions=settings.file_extensions,
        lang=lang,
        lenient=True,
    )
    for section_id, flavor, context in _shared_flavor_contexts(settings):
        try:
            deck = shared_parser.from_section(section_id, flavor)
        except DeckzError as e:
            acc.report.structural.append((context, str(e)))
            continue
        _walk_deck(deck, shared_base_variables, renderer, acc)

    for deck_settings in all_deck_settings(git_dir):
        deck_context = str(
            deck_settings.paths.deck_definition.parent.relative_to(git_dir)
        )
        deck_parser = Parser(
            local_latex_dir=deck_settings.paths.local_latex_dir,
            shared_latex_dir=deck_settings.paths.latex_dir,
            file_extensions=deck_settings.file_extensions,
            lang=lang,
            lenient=True,
        )
        try:
            deck = deck_parser.from_deck_definition(deck_settings.paths.deck_definition)
        except DeckzError as e:
            acc.report.structural.append((deck_context, str(e)))
            continue
        deck_base_variables = {**get_variables(deck_settings, lang), "lang": lang}
        _walk_deck(deck, deck_base_variables, renderer, acc)

    for yml_path, declared in acc.declared.items():
        for name in sorted(declared - acc.referenced.get(yml_path, set())):
            acc.report.unused.append((yml_path, name))

    return acc.report
