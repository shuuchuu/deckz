from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter, ValidationError
from yaml import safe_load

from .models import (
    Deck,
    DeckConfig,
    File,
    FileInclude,
    Node,
    Part,
    PartDefinition,
    Section,
    SectionDefinition,
    SectionInclude,
)


class DeckBuilder:
    def __init__(self, local_latex_dir: Path, shared_latex_dir: Path) -> None:
        self._local_latex_dir = local_latex_dir
        self._shared_latex_dir = shared_latex_dir

    def from_targets(self, deck_config_path: Path, targets_path: Path) -> Deck:
        content = safe_load(deck_config_path.read_text(encoding="utf8"))
        deck_config = DeckConfig.model_validate(content)

        content = safe_load(targets_path.read_text(encoding="utf8"))
        adapter = TypeAdapter(list[PartDefinition])
        part_definitions = adapter.validate_python(content)

        return Deck(
            acronym=deck_config.deck_acronym, parts=self._parse_parts(part_definitions)
        )

    def from_section(self, section: str, flavor: str) -> Deck:
        return Deck(
            acronym="deck",
            parts=self._parse_parts(
                [
                    PartDefinition.model_construct(
                        name="part_name",
                        sections=[SectionInclude(path=Path(section), flavor=flavor)],
                    )
                ]
            ),
        )

    def from_file(self, latex: str) -> Deck:
        return Deck(
            acronym="deck",
            parts=self._parse_parts(
                [
                    PartDefinition.model_construct(
                        name="part_name",
                        sections=[FileInclude(path=Path(latex))],
                    )
                ]
            ),
        )

    def _parse_parts(self, part_definitions: list[PartDefinition]) -> dict[str, Part]:
        parts = {}
        for part_definition in part_definitions:
            part_nodes: list[Node] = []
            for node_include in part_definition.sections:
                if isinstance(node_include, SectionInclude):
                    part_nodes.append(
                        self._parse_section(
                            base_logical_path=Path("/"),
                            logical_path=node_include.path,
                            title=node_include.title,
                            flavor=node_include.flavor,
                        )
                    )
                else:
                    part_nodes.append(
                        self._parse_file(
                            base_logical_path=Path("/"),
                            logical_path=node_include.path,
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
        base_logical_path: Path,
        logical_path: Path,
        title: str | None,
        flavor: str,
    ) -> Section:
        logical_path = self._compute_logical_path(base_logical_path, logical_path)
        section = Section(
            title=title,
            logical_path=logical_path,
            path=logical_path,
            parsing_error=None,
            flavor=flavor,
            children=[],
        )
        resolved_path = self._resolve(logical_path, resolve_target="dir")
        if resolved_path:
            section.path = resolved_path
        else:
            section.parsing_error = f"unresolvable section path {logical_path}"
            return section
        definition_logical_path = (logical_path / logical_path.name).with_suffix(".yml")
        definition_resolved_path = self._resolve(
            definition_logical_path.with_suffix(".yml"), "file"
        )
        if definition_resolved_path is None:
            section.parsing_error = (
                f"unresolvable section definition path {definition_logical_path}"
            )
            return section
        try:
            content = safe_load(definition_resolved_path.read_text(encoding="utf8"))
        except Exception as e:
            section.parsing_error = f"{e}"
            return section
        try:
            section_definition = SectionDefinition.model_validate(content)
        except ValidationError as e:
            section.parsing_error = f"{e}"
            return section
        if section.title is None:
            section.title = section_definition.title
        if flavor not in section_definition.flavors:
            section.parsing_error = f"flavor {flavor} not found"
            return section
        for node_include in section_definition.flavors[flavor]:
            if node_include.title:
                title = node_include.title
            elif (
                not node_include.title_unset
                and section_definition.default_titles
                and node_include.path in section_definition.default_titles
            ):
                title = section_definition.default_titles[node_include.path]
            else:
                title = None
            if isinstance(node_include, FileInclude):
                section.children.append(
                    self._parse_file(
                        base_logical_path=logical_path,
                        logical_path=node_include.path,
                        title=title,
                    )
                )
            else:
                section.children.append(
                    self._parse_section(
                        base_logical_path=logical_path,
                        logical_path=node_include.path,
                        title=title,
                        flavor=node_include.flavor,
                    )
                )
        return section

    def _parse_file(
        self, base_logical_path: Path, logical_path: Path, title: str | None
    ) -> File:
        logical_path = self._compute_logical_path(base_logical_path, logical_path)
        file = File(
            title=title,
            logical_path=logical_path,
            path=logical_path,
            parsing_error=None,
        )
        resolved_path = self._resolve(logical_path.with_suffix(".tex"), "file")
        if resolved_path:
            file.path = resolved_path
        else:
            file.parsing_error = f"unresolvable file path {logical_path}"
        return file

    @staticmethod
    def _compute_logical_path(base_logical_path: Path, logical_path: Path) -> Path:
        return logical_path if logical_path.root else base_logical_path / logical_path

    def _resolve(
        self, logical_path: Path, resolve_target: Literal["file", "dir"]
    ) -> Path | None:
        relative_logical_path = logical_path.relative_to("/")
        local_path = self._local_latex_dir / relative_logical_path
        shared_path = self._shared_latex_dir / relative_logical_path
        existence_tester = Path.is_file if resolve_target == "file" else Path.is_dir
        for path in [local_path, shared_path]:
            if existence_tester(path):
                return path.resolve()
        return None
