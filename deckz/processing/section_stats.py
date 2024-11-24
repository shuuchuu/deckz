from collections.abc import MutableSet
from pathlib import Path

from ..models.deck import Deck, File, Part, Section
from . import NodeVisitor, Processor


class SectionStatsProcessor(Processor):
    def __init__(self) -> None:
        self._node_visitor = _SectionStatsNodeVisitor()

    def process(self, deck: Deck) -> dict[str, set[tuple[Path, str]]]:
        return {
            part_name: self._process_part(part)
            for part_name, part in deck.parts.items()
        }

    def _process_part(self, part: Part) -> dict[Path, set[str]]:
        section_stats = set()
        for node in part.nodes:
            node.accept(self._node_visitor, section_stats)
        return section_stats


class _SectionStatsNodeVisitor(NodeVisitor):
    def visit_file(
        self, file: File, section_stats: MutableSet[tuple[Path, str]]
    ) -> None:
        pass

    def visit_section(
        self, section: Section, section_stats: MutableSet[tuple[Path, str]]
    ) -> None:
        section_stats.add((section.logical_path, section.flavor))
        for node in section.children:
            node.accept(self, section_stats)
