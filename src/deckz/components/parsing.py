from collections.abc import Iterable
from pathlib import Path, PurePath
from sys import stderr
from typing import ClassVar, Literal

from pydantic import ValidationError
from rich import print as rich_print
from rich.tree import Tree

from ..exceptions import DeckzError
from ..models.deck import Deck, File, Node, Part, Section
from ..models.definitions import (
    DeckDefinition,
    FileInclude,
    NodeInclude,
    PartDefinition,
    SectionDefinition,
    SectionInclude,
)
from ..models.scalars import (
    FlavorName,
    IncludePath,
    PartName,
    ResolvedPath,
    UnresolvedPath,
)
from ..processing import NodeVisitor
from ..utils import load_yaml
from . import Parser, ParserConfig


class DefaultParser(Parser):
    """Build a deck from a definition.

    The definition can be a complete deck definition obtained from a yaml file or a \
    simpler one obtained from a single section or file.
    """

    def __init__(
        self,
        local_latex_dir: Path,
        shared_latex_dir: Path,
        config: "DefaultParserConfig",
    ) -> None:
        """Initialize an instance with the necessary path information.

        Args:
            local_latex_dir: Path to the local latex directory. Used during the \
                includes resolving process
            shared_latex_dir: Path to the shared latex directory. Used during the \
                includes resolving process
            config: Configuration retrieved from configuration files for this component.
        """
        self._local_latex_dir = local_latex_dir
        self._shared_latex_dir = shared_latex_dir
        self._config = config

    def from_deck_definition(self, deck_definition_path: Path) -> Deck:
        """Parse a deck from a yaml definition.

        Args:
            deck_definition_path: Path to the yaml definition. It should be parsable \
                into a [deckz.models.definitions.DeckDefinition][] by Pydantic

        Returns:
            The parsed deck
        """
        deck_definition = DeckDefinition.model_validate(load_yaml(deck_definition_path))
        return Deck(
            name=deck_definition.name, parts=self._parse_parts(deck_definition.parts)
        )

    def from_section(self, section: str, flavor: FlavorName) -> Deck:
        return Deck(
            name="deck",
            parts=self._parse_parts(
                [
                    PartDefinition.model_construct(
                        name=PartName("part_name"),
                        sections=[
                            SectionInclude(
                                path=IncludePath(PurePath(section)), flavor=flavor
                            )
                        ],
                    )
                ]
            ),
        )

    def from_file(self, latex: str) -> Deck:
        return Deck(
            name="deck",
            parts=self._parse_parts(
                [
                    PartDefinition.model_construct(
                        name=PartName("part_name"),
                        sections=[FileInclude(path=IncludePath(PurePath(latex)))],
                    )
                ]
            ),
        )

    def _parse_parts(
        self, part_definitions: list[PartDefinition]
    ) -> dict[PartName, Part]:
        parts = {}
        for part_definition in part_definitions:
            part_nodes: list[Node] = []
            for node_include in part_definition.sections:
                if isinstance(node_include, SectionInclude):
                    part_nodes.append(
                        self._parse_section(
                            base_unresolved_path=UnresolvedPath(PurePath()),
                            include_path=node_include.path,
                            title=node_include.title,
                            title_unset="title" not in node_include.model_fields_set,
                            flavor=node_include.flavor,
                        )
                    )
                else:
                    part_nodes.append(
                        self._parse_file(
                            base_unresolved_path=UnresolvedPath(PurePath()),
                            include_path=node_include.path,
                            title=node_include.title,
                        )
                    )
            parts[part_definition.name] = Part(
                title=part_definition.title,
                nodes=part_nodes,
            )
        return parts

    def _parse_section(
        self,
        base_unresolved_path: UnresolvedPath,
        include_path: IncludePath,
        title: str | None,
        title_unset: bool,
        flavor: FlavorName,
    ) -> Section:
        unresolved_path = self._compute_unresolved_path(
            base_unresolved_path, include_path
        )
        section = Section(
            title=title,
            unresolved_path=unresolved_path,
            resolved_path=ResolvedPath(Path()),
            parsing_error=None,
            flavor=flavor,
            nodes=[],
        )
        definition_logical_path = (unresolved_path / unresolved_path.name).with_suffix(
            ".yml"
        )
        definition_resolved_path = self._resolve(
            definition_logical_path.with_suffix(".yml"), "file"
        )
        if definition_resolved_path is None:
            section.parsing_error = (
                f"unresolvable section definition path {definition_logical_path}"
            )
            return section
        section.resolved_path = definition_resolved_path.parent
        try:
            content = load_yaml(definition_resolved_path)
        except Exception as e:
            section.parsing_error = f"{e}"
            return section
        try:
            section_definition = SectionDefinition.model_validate(content)
        except ValidationError as e:
            section.parsing_error = f"{e}"
            return section
        for flavor_definition in section_definition.flavors:
            if flavor_definition.name == flavor:
                break
        else:
            section.parsing_error = f"flavor {flavor} not found"
            return section
        if title_unset:
            if "title" in flavor_definition.model_fields_set:
                section.title = flavor_definition.title
            else:
                section.title = section_definition.title
        section.nodes.extend(
            self._parse_nodes(
                flavor_definition.includes,
                default_titles=section_definition.default_titles,
                base_unresolved_path=unresolved_path,
            )
        )
        return section

    def _parse_nodes(
        self,
        node_includes: Iterable[NodeInclude],
        default_titles: dict[IncludePath, str] | None,
        base_unresolved_path: UnresolvedPath,
    ) -> list[Node]:
        nodes: list[Node] = []
        for node_include in node_includes:
            if node_include.title:
                title = node_include.title
            elif (
                "title" not in node_include.model_fields_set
                and default_titles
                and node_include.path in default_titles
            ):
                title = default_titles[node_include.path]
            else:
                title = None
            if isinstance(node_include, FileInclude):
                nodes.append(
                    self._parse_file(
                        base_unresolved_path=base_unresolved_path,
                        include_path=node_include.path,
                        title=title,
                    )
                )
            if isinstance(node_include, SectionInclude):
                nodes.append(
                    self._parse_section(
                        base_unresolved_path=base_unresolved_path,
                        include_path=node_include.path,
                        title=title,
                        title_unset="title" not in node_include.model_fields_set,
                        flavor=node_include.flavor,
                    )
                )
        return nodes

    def _parse_file(
        self,
        base_unresolved_path: UnresolvedPath,
        include_path: IncludePath,
        title: str | None,
    ) -> File:
        unresolved_path = self._compute_unresolved_path(
            base_unresolved_path, include_path
        )
        file = File(
            title=title,
            unresolved_path=unresolved_path,
            resolved_path=ResolvedPath(Path()),
            parsing_error=None,
        )
        resolved_path = self._resolve(
            unresolved_path.with_suffix(self._config.file_extension), "file"
        )
        if resolved_path:
            file.resolved_path = resolved_path
        else:
            file.parsing_error = f"unresolvable file path {unresolved_path}"
        return file

    @staticmethod
    def _compute_unresolved_path(
        base_unresolved_path: UnresolvedPath, include_path: IncludePath
    ) -> UnresolvedPath:
        return UnresolvedPath(
            include_path.relative_to("/")
            if include_path.root
            else base_unresolved_path / include_path
        )

    def _resolve(
        self, unresolved_path: UnresolvedPath, resolve_target: Literal["file", "dir"]
    ) -> ResolvedPath | None:
        local_path = self._local_latex_dir / unresolved_path
        shared_path = self._shared_latex_dir / unresolved_path
        existence_tester = Path.is_file if resolve_target == "file" else Path.is_dir
        for path in [local_path, shared_path]:
            if existence_tester(path):
                return ResolvedPath(path.resolve())
        return None

    def _validate(self, deck: Deck) -> None:
        tree = _RichTreeVisitor().process(deck)
        if tree is not None:
            rich_print(tree, file=stderr)
            msg = "deck parsing failed"
            raise DeckzError(msg)


class DefaultParserConfig(ParserConfig, component=DefaultParser):
    file_extension: str = ".tex"

    config_key: ClassVar[Literal["default_parser"]] = "default_parser"


class _RichTreeVisitor(NodeVisitor[[UnresolvedPath], tuple[Tree | None, bool]]):
    def __init__(self, only_errors: bool = True) -> None:
        self._only_errors = only_errors

    def process(self, deck: Deck) -> Tree | None:
        part_trees = []
        for part_name, part in deck.parts.items():
            part_tree = self._process_part(part_name, part)
            if part_tree is not None:
                part_trees.append(part_tree)

        if part_trees:
            tree = Tree(deck.name)
            tree.children.extend(part_trees)
            return tree
        return None

    def _process_part(self, part_name: PartName, part: Part) -> Tree | None:
        error = False
        children_trees = []
        for child in part.nodes:
            child_tree, child_error = child.accept(self, UnresolvedPath(PurePath()))
            error = error or child_error
            if child_tree is not None:
                children_trees.append(child_tree)

        if self._only_errors and not error:
            return None

        tree = Tree(part_name)
        tree.children.extend(children_trees)
        return tree

    def visit_file(
        self, file: File, base_path: UnresolvedPath
    ) -> tuple[Tree | None, bool]:
        if self._only_errors and file.parsing_error is None:
            return None, False
        path = (
            file.unresolved_path.relative_to(base_path)
            if file.unresolved_path.is_relative_to(base_path)
            else file.unresolved_path
        )
        if file.parsing_error is None:
            return Tree(str(path)), False
        return Tree(f"[red]{path} ({file.parsing_error})[/]"), True

    def visit_section(
        self, section: Section, base_path: UnresolvedPath
    ) -> tuple[Tree | None, bool]:
        error = section.parsing_error is not None
        children_trees = []
        for child in section.nodes:
            child_tree, child_error = child.accept(self, section.unresolved_path)
            error = error or child_error
            if child_tree is not None:
                children_trees.append(child_tree)

        if self._only_errors and not error:
            return None, False

        path = (
            section.unresolved_path.relative_to(base_path)
            if section.unresolved_path.is_relative_to(base_path)
            else section.unresolved_path
        )

        if section.parsing_error is not None:
            label = f"[red]{path}@{section.flavor} ({section.parsing_error})[/]"
        else:
            label = f"{path}@{section.flavor}"

        tree = Tree(label)
        tree.children.extend(children_trees)

        return tree, error
