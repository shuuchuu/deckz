from collections.abc import MutableSet
from pathlib import Path

from ..tree_parsing import Deck, File, Part, Section


class DependenciesVisitor:
    def visit_file(self, file: File, dependencies: MutableSet[Path]) -> None:
        dependencies.add(file.path)

    def visit_section(self, section: Section, dependencies: MutableSet[Path]) -> None:
        for node in section.children:
            node.accept(self, dependencies)

    def process_part(self, part: Part) -> set[Path]:
        dependencies: set[Path] = set()
        for node in part.nodes:
            node.accept(self, dependencies)
        return dependencies

    def process_deck(self, deck: Deck) -> dict[str, set[Path]]:
        return {
            part_name: self.process_part(part) for part_name, part in deck.parts.items()
        }
