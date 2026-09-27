from collections.abc import Iterable
from os.path import normpath
from pathlib import Path, PurePath
from typing import Literal

from pydantic import ValidationError

from ..exceptions import DeckParsingError, InvalidConfigurationError
from ..models import (
    Deck,
    DeckDefinition,
    File,
    FileInclude,
    FlavorName,
    IncludePath,
    Lang,
    Node,
    NodeInclude,
    NodeVisitor,
    Part,
    PartDefinition,
    PartName,
    ResolvedPath,
    Section,
    SectionDefinition,
    SectionInclude,
    UnresolvedPath,
)
from ..utils import load_yaml
from .protocols import ParserProtocol


class Parser(ParserProtocol):
    """Build a deck from a definition.

    The definition can be a complete deck definition obtained from a yaml file or a \
    simpler one obtained from a single section or file.
    """

    def __init__(
        self,
        local_content_dir: Path,
        shared_content_dir: Path,
        file_extensions: Iterable[str],
        lang: Lang = "fr",
        *,
        lenient: bool = False,
    ) -> None:
        """Initialize an instance with the necessary path information.

        Args:
            local_content_dir: Path to the local content directory. Used during the \
                includes resolving process
            shared_content_dir: Path to the shared content directory. Used during the \
                includes resolving process
            file_extensions: Extensions to try, in order, when resolving a file \
                include (e.g. `(".md", ".typ")` to prefer a Markdown file \
                and fall back to a raw Typst one).
            lang: Language to resolve the deck/sections in. Affects which \
                physical body file is picked for each leaf file node (an "en" \
                sibling is required, with no fallback to fr) and which string a \
                title/translation map resolves to.
            lenient: If True, a title/translation map missing `lang` falls \
                back instead of raising. Used only by the i18n coverage \
                check, which must be able to walk a deck's whole tree \
                precisely to report the translation gaps that would \
                otherwise make a real build fail.
        """
        self._local_content_dir = local_content_dir
        self._shared_content_dir = shared_content_dir
        self._file_extensions = tuple(file_extensions)
        self._lang = lang
        self._lenient = lenient

    def from_deck_definition(self, deck_definition_path: Path) -> Deck:
        """Parse a deck from a yaml definition.

        Args:
            deck_definition_path: Path to the yaml definition. It should be parsable \
                into a [`DeckDefinition`][deckz.models.DeckDefinition] by Pydantic

        Returns:
            The parsed deck

        Raises:
            InvalidConfigurationError: If the definition is missing, isn't \
                valid YAML or doesn't match the expected schema.
        """
        if not deck_definition_path.is_file():
            msg = (
                f"no deck definition found at {deck_definition_path}, run this "
                "command from inside a deck"
            )
            raise InvalidConfigurationError(msg)
        try:
            deck_definition = DeckDefinition.model_validate(
                load_yaml(deck_definition_path),
                context={"lang": self._lang, "lenient": self._lenient},
            )
        except ValidationError as e:
            msg = f"{deck_definition_path} is not a valid deck definition:\n{e}"
            raise InvalidConfigurationError(msg) from e
        deck = Deck(
            name=deck_definition.name, parts=self._parse_parts(deck_definition.parts)
        )
        self.validate(deck)
        return deck

    def from_section(self, section: str, flavor: FlavorName) -> Deck:
        deck = Deck(
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
        self.validate(deck)
        return deck

    def all_files_section(self, section: str) -> Section:
        """Build a section from every file physically present in its directory.

        Args:
            section: Shared/content-relative section id, e.g. "python/basics".

        Returns:
            The built section.
        """
        return self._all_files_section(UnresolvedPath(PurePath(section)))

    def _all_files_section(self, unresolved_path: UnresolvedPath) -> Section:
        section_dir = self._shared_content_dir / unresolved_path
        section = Section(
            title=None,
            unresolved_path=unresolved_path,
            resolved_path=ResolvedPath(section_dir),
            parsing_error=None,
            flavor=FlavorName("all"),
            nodes=[],
        )
        definition_path = section_dir / f"{unresolved_path.name}.yml"
        if not definition_path.is_file():
            section.parsing_error = (
                f"unresolvable section definition path {definition_path}"
            )
            return section
        try:
            content = load_yaml(definition_path)
        except (InvalidConfigurationError, OSError) as e:
            section.parsing_error = f"{e}"
            return section
        try:
            section_definition = SectionDefinition.model_validate(
                content, context={"lang": self._lang, "lenient": self._lenient}
            )
        except ValidationError as e:
            section.parsing_error = f"{e}"
            return section
        section.title = section_definition.title
        default_titles = section_definition.default_titles
        stems = sorted(
            {
                path.stem
                for path in section_dir.iterdir()
                if path.is_file() and path.suffix in self._file_extensions
            }
        )
        section.nodes = [
            self._parse_file(
                base_unresolved_path=unresolved_path,
                include_path=IncludePath(PurePath(stem)),
                title=(
                    default_titles.get(IncludePath(PurePath(stem)))
                    if default_titles
                    else None
                ),
            )
            for stem in stems
        ]
        return section

    def from_file(self, path: str) -> Deck:
        deck = Deck(
            name="deck",
            parts=self._parse_parts(
                [
                    PartDefinition.model_construct(
                        name=PartName("part_name"),
                        sections=[FileInclude(path=IncludePath(PurePath(path)))],
                    )
                ]
            ),
        )
        self.validate(deck)
        return deck

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
            definition_logical_path.with_suffix(".yml"), "file", lang_aware=False
        )
        if definition_resolved_path is None:
            section.parsing_error = (
                f"unresolvable section definition path {definition_logical_path}"
            )
            return section
        section.resolved_path = definition_resolved_path.parent
        try:
            content = load_yaml(definition_resolved_path)
        except (InvalidConfigurationError, OSError) as e:
            section.parsing_error = f"{e}"
            return section
        try:
            section_definition = SectionDefinition.model_validate(
                content, context={"lang": self._lang, "lenient": self._lenient}
            )
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
        section.variables = dict(flavor_definition.variables or {})
        missing = [
            declaration.name
            for declaration in section_definition.variables_to_define
            if declaration.name not in section.variables
        ]
        if missing:
            section.parsing_error = (
                f"flavor {flavor} does not define variable(s): "
                f"{', '.join(sorted(missing))}"
            )
            return section
        invalid = [
            f"{declaration.name}={section.variables[declaration.name]!r} "
            f"not in {declaration.allowed_values}"
            for declaration in section_definition.variables_to_define
            if declaration.allowed_values is not None
            and section.variables[declaration.name] not in declaration.allowed_values
        ]
        if invalid:
            section.parsing_error = (
                f"flavor {flavor} has invalid variable value(s): {'; '.join(invalid)}"
            )
            return section
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
        resolved_path = None
        for file_extension in self._file_extensions:
            resolved_path = self._resolve(
                unresolved_path.with_suffix(file_extension), "file"
            )
            if resolved_path:
                break
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
            else PurePath(normpath(base_unresolved_path / include_path))
        )

    def _resolve(
        self,
        unresolved_path: UnresolvedPath,
        resolve_target: Literal["file", "dir"],
        *,
        lang_aware: bool = True,
    ) -> ResolvedPath | None:
        local_path = self._local_content_dir / unresolved_path
        shared_path = self._shared_content_dir / unresolved_path
        existence_tester = Path.is_file if resolve_target == "file" else Path.is_dir
        if lang_aware and resolve_target == "file" and self._lang == "en":
            # No fr fallback: a missing en/ sibling under --en must fail loudly
            # rather than silently compiling fr content under an English label.
            candidates = [
                local_path.parent / "en" / local_path.name,
                shared_path.parent / "en" / shared_path.name,
            ]
        else:
            candidates = [local_path, shared_path]
        for path in candidates:
            if existence_tester(path):
                return ResolvedPath(path.resolve())
        return None

    @staticmethod
    def validate(deck: Deck) -> None:
        finder = _ErrorFinderNodeVisitor()
        errors = [
            error
            for part in deck.parts.values()
            for node in part.nodes
            for error in node.accept(finder)
        ]
        if errors:
            raise DeckParsingError(deck, errors)


class _ErrorFinderNodeVisitor(NodeVisitor[[], list[str]]):
    def visit_file(self, file: File) -> list[str]:
        if file.parsing_error is None:
            return []
        return [f"{file.unresolved_path} ({file.parsing_error})"]

    def visit_section(self, section: Section) -> list[str]:
        errors = (
            [f"{section.unresolved_path}@{section.flavor} ({section.parsing_error})"]
            if section.parsing_error is not None
            else []
        )
        for node in section.nodes:
            errors.extend(node.accept(self))
        return errors
