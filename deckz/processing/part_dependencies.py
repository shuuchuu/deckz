from collections.abc import MutableSet

from ..models.deck import Deck, File, Part, Section
from ..models.scalars import ResolvedPath
from . import NodeVisitor, Processor


class PartDependenciesProcessor(Processor[dict[str, set[ResolvedPath]]]):
    def __init__(self) -> None:
        self._node_visitor = _PartDependenciesNodeVisitor()

    def process(self, deck: Deck) -> dict[str, set[ResolvedPath]]:
        return {
            part_name: self._process_part(part)
            for part_name, part in deck.parts.items()
        }

    def _process_part(self, part: Part) -> set[ResolvedPath]:
        dependencies: set[ResolvedPath] = set()
        for node in part.nodes:
            node.accept(self._node_visitor, dependencies)
        return dependencies


class _PartDependenciesNodeVisitor(NodeVisitor[[MutableSet[ResolvedPath]], None]):
    def visit_file(self, file: File, dependencies: MutableSet[ResolvedPath]) -> None:
        dependencies.add(file.resolved_path)

    def visit_section(
        self, section: Section, dependencies: MutableSet[ResolvedPath]
    ) -> None:
        for node in section.children:
            node.accept(self, dependencies)
