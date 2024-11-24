from collections.abc import MutableMapping, MutableSet
from pathlib import Path
from typing import cast

from ..models import Deck, File, Part, Section
from . import NodeVisitor, Processor


class SectionDependenciesProcessor(Processor[dict[Path, set[Path]]]):
    def __init__(self) -> None:
        self._node_visitor = _SectionDependenciesNodeVisitor()

    def process(self, deck: Deck) -> dict[Path, set[Path]]:
        dependencies: dict[Path, set[Path]] = {}
        for part in deck.parts.values():
            self._process_part(
                part, cast(MutableMapping[Path, MutableSet[Path]], dependencies)
            )
        return dependencies

    def _process_part(
        self, part: Part, dependencies: MutableMapping[Path, MutableSet[Path]]
    ) -> None:
        for node in part.nodes:
            node.accept(self._node_visitor, dependencies, Path("/"))


class _SectionDependenciesNodeVisitor(
    NodeVisitor[[MutableMapping[Path, MutableSet[Path]], Path], None]
):
    def visit_file(
        self,
        file: File,
        section_dependencies: MutableMapping[Path, MutableSet[Path]],
        current_logical_path: Path,
    ) -> None:
        if current_logical_path not in section_dependencies:
            section_dependencies[current_logical_path] = set()
        section_dependencies[current_logical_path].add(file.path)

    def visit_section(
        self,
        section: Section,
        section_dependencies: MutableMapping[Path, MutableSet[Path]],
        current_logical_path: Path,
    ) -> None:
        for node in section.children:
            node.accept(self, section_dependencies, section.logical_path)
