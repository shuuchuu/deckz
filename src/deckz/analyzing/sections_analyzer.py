from collections.abc import MutableMapping, MutableSet
from functools import cached_property
from pathlib import Path, PurePath
from typing import cast

from ..models import (
    Deck,
    File,
    FlavorName,
    NodeVisitor,
    Part,
    PartName,
    Section,
    SectionDefinition,
    UnresolvedPath,
)
from ..utils import all_decks, load_yaml


class SectionsAnalyzer:
    def __init__(self, shared_latex_dir: Path, git_dir: Path) -> None:
        self._shared_latex_dir = shared_latex_dir
        self._git_dir = git_dir

    def unused_flavors(self) -> dict[UnresolvedPath, set[FlavorName]]:
        unused_flavors = {
            p: {f.name for f in d.flavors} for p, d in self._shared_sections.items()
        }
        for section_stats in self._sections_usage.values():
            for section_flavors in section_stats.values():
                for path, flavors in section_flavors.items():
                    for flavor in flavors:
                        if path in unused_flavors and flavor in unused_flavors[path]:
                            unused_flavors[path].remove(flavor)
                            if not unused_flavors[path]:
                                del unused_flavors[path]
        return unused_flavors

    def parts_using_flavor(
        self,
        section: str,
        flavor: str | None,
    ) -> dict[Path, set[PartName]]:
        section_path = UnresolvedPath(PurePath(section))
        using: dict[Path, set[PartName]] = {}
        for deck_path, section_stats in self._sections_usage.items():
            for part_name, section_flavors in section_stats.items():
                for path, flavors in section_flavors.items():
                    if path == section_path and (flavor is None or flavor in flavors):
                        if deck_path not in using:
                            using[deck_path] = set()
                        using[deck_path].add(part_name)
        return using

    @cached_property
    def _decks(self) -> dict[Path, Deck]:
        return all_decks(self._git_dir)

    @cached_property
    def _shared_sections(self) -> dict[UnresolvedPath, SectionDefinition]:
        result = {}
        for path in self._shared_latex_dir.rglob("*.yml"):
            content = load_yaml(path)
            result[UnresolvedPath(path.parent.relative_to(self._shared_latex_dir))] = (
                SectionDefinition.model_validate(content)
            )
        return result

    @cached_property
    def _sections_usage(
        self,
    ) -> dict[Path, dict[PartName, dict[UnresolvedPath, set[FlavorName]]]]:
        """Compute sections usage over all decks.

        Returns:
            Nested dictionaries: deck path -> part name -> section path -> flavor.
        """
        section_stats_processor = _SectionsUsageNodeVisitor(self._shared_latex_dir)
        return {
            deck_path: section_stats_processor.process(deck)
            for deck_path, deck in self._decks.items()
        }


class _SectionsUsageNodeVisitor(
    NodeVisitor[[MutableMapping[UnresolvedPath, MutableSet[FlavorName]]], None]
):
    def __init__(self, shared_latex_dir: Path) -> None:
        self._shared_latex_dir = shared_latex_dir

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
                self,
                # Not sure why we need a cast here :/
                cast(
                    "MutableMapping[UnresolvedPath, MutableSet[FlavorName]]",
                    section_stats,
                ),
            )
        return section_stats

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
