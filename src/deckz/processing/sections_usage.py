from collections.abc import MutableMapping, MutableSet
from pathlib import Path
from typing import cast

from ..models.deck import Deck, File, Part, Section
from ..models.scalars import FlavorName, PartName, UnresolvedPath
from . import NodeVisitor, Processor


class SectionsUsageProcessor(
    Processor[dict[PartName, dict[UnresolvedPath, set[FlavorName]]]]
):
    def __init__(self, shared_latex_dir: Path) -> None:
        self._node_visitor = _SectionsUsageNodeVisitor(shared_latex_dir)

    def process(
        self, deck: Deck
    ) -> dict[PartName, dict[UnresolvedPath, set[FlavorName]]]:
        return {
            part_name: self._process_part(part)
            for part_name, part in deck.parts.items()
        }

    def _process_part(self, part: Part) -> dict[UnresolvedPath, set[FlavorName]]:
        section_stats: dict[UnresolvedPath, set[FlavorName]] = {}
        for node in part.nodes:
            node.accept(
                self._node_visitor,
                # Not sure why we need a cast here :/
                cast(
                    MutableMapping[UnresolvedPath, MutableSet[FlavorName]],
                    section_stats,
                ),
            )
        return section_stats


class _SectionsUsageNodeVisitor(
    NodeVisitor[[MutableMapping[UnresolvedPath, MutableSet[FlavorName]]], None]
):
    def __init__(self, shared_latex_dir: Path) -> None:
        self._shared_latex_dir = shared_latex_dir

    def visit_file(
        self,
        file: File,
        section_stats: MutableMapping[UnresolvedPath, MutableSet[FlavorName]],
    ) -> None:
        pass

    def visit_section(
        self,
        section: Section,
        section_stats: MutableMapping[UnresolvedPath, MutableSet[FlavorName]],
    ) -> None:
        if section.resolved_path.is_relative_to(self._shared_latex_dir):
            if section.unresolved_path not in section_stats:
                section_stats[section.unresolved_path] = set()
            section_stats[section.unresolved_path].add(section.flavor)
        for node in section.nodes:
            node.accept(self, section_stats)
