from collections.abc import MutableSet
from pathlib import Path

from ..models import Deck, File, Part, Section
from . import NodeVisitor, Processor


class DependenciesProcessor(Processor[dict[str, set[Path]]]):
    def __init__(self) -> None:
        self._node_visitor = _DependenciesNodeVisitor()

    def process(self, deck: Deck) -> dict[str, set[Path]]:
        return {
            part_name: self._process_part(part)
            for part_name, part in deck.parts.items()
        }

    def _process_part(self, part: Part) -> set[Path]:
        dependencies: set[Path] = set()
        for node in part.nodes:
            node.accept(self._node_visitor, dependencies)
        return dependencies


class _DependenciesNodeVisitor(NodeVisitor[[MutableSet[Path]], None]):
    def visit_file(self, file: File, dependencies: MutableSet[Path]) -> None:
        dependencies.add(file.path)

    def visit_section(self, section: Section, dependencies: MutableSet[Path]) -> None:
        for node in section.children:
            node.accept(self, dependencies)
