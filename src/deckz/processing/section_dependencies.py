from collections.abc import MutableMapping, MutableSet
from pathlib import PurePath
from typing import cast

from ..models.deck import Deck, File, Part, Section
from ..models.scalars import ResolvedPath, UnresolvedPath
from . import NodeVisitor, Processor


class SectionDependenciesProcessor(Processor[dict[UnresolvedPath, set[ResolvedPath]]]):
    def __init__(self) -> None:
        self._node_visitor = _SectionDependenciesNodeVisitor()

    def process(self, deck: Deck) -> dict[UnresolvedPath, set[ResolvedPath]]:
        dependencies: dict[UnresolvedPath, set[ResolvedPath]] = {}
        for part in deck.parts.values():
            self._process_part(
                part,
                cast(
                    MutableMapping[UnresolvedPath, MutableSet[ResolvedPath]],
                    dependencies,
                ),
            )
        return dependencies

    def _process_part(
        self,
        part: Part,
        dependencies: MutableMapping[UnresolvedPath, MutableSet[ResolvedPath]],
    ) -> None:
        for node in part.nodes:
            node.accept(self._node_visitor, dependencies, UnresolvedPath(PurePath()))


class _SectionDependenciesNodeVisitor(
    NodeVisitor[
        [MutableMapping[UnresolvedPath, MutableSet[ResolvedPath]], UnresolvedPath], None
    ]
):
    def visit_file(
        self,
        file: File,
        section_dependencies: MutableMapping[UnresolvedPath, MutableSet[ResolvedPath]],
        base_unresolved_path: UnresolvedPath,
    ) -> None:
        if base_unresolved_path not in section_dependencies:
            section_dependencies[base_unresolved_path] = set()
        section_dependencies[base_unresolved_path].add(file.resolved_path)

    def visit_section(
        self,
        section: Section,
        section_dependencies: MutableMapping[UnresolvedPath, MutableSet[ResolvedPath]],
        base_unresolved_path: UnresolvedPath,
    ) -> None:
        for node in section.nodes:
            node.accept(self, section_dependencies, section.unresolved_path)
