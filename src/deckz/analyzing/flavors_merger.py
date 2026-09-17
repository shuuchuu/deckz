from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import FlavorDefinition, FlavorName, SectionInclude, UnresolvedPath
from .flavor_files import FlavorFilesEditor, RenameMap, SectionEdit


@dataclass(frozen=True)
class FlavorsMerge:
    """A group of identical flavors found in a single section."""

    section: UnresolvedPath
    """Path of the section the flavors belong to, relative to its latex directory."""

    kept: FlavorName
    """Name of the flavor that was kept."""

    removed: frozenset[FlavorName]
    """Names of the flavors that were merged into \
    [`kept`][deckz.analyzing.flavors_merger.FlavorsMerge.kept]."""


class FlavorsMerger:
    """Find and merge sections' flavors that are identical up to their name."""

    def __init__(self, git_dir: Path, shared_latex_dir: Path) -> None:
        self._editor = FlavorFilesEditor(git_dir, shared_latex_dir)

    def merge(self, *, dry_run: bool = False) -> list[FlavorsMerge]:
        """Find identical flavors and, unless `dry_run`, merge them.

        Merging a group of identical flavors means keeping only one of them (the \
        first one, in the section definition order) and rewriting every reference \
        to the removed ones, in every deck and section of the repository, to point \
        to the kept flavor instead.

        Args:
            dry_run: Only find and report the merges, without applying them

        Returns:
            The list of merges found (and applied, unless `dry_run`).
        """
        latex_directories = self._editor.latex_directories()
        definitions = self._editor.section_definitions(latex_directories)

        rename_map: dict[UnresolvedPath, dict[FlavorName, FlavorName]] = {}
        merges: list[FlavorsMerge] = []
        for path, definition in definitions.items():
            unresolved_section = self._editor.unresolved_path(path, latex_directories)
            renames = self._find_duplicates(definition.flavors)
            if not renames:
                continue
            rename_map[unresolved_section] = renames
            for kept, removed in self._group_by_kept(renames).items():
                merges.append(
                    FlavorsMerge(unresolved_section, kept, frozenset(removed))
                )

        if not dry_run and rename_map:
            for path in definitions:
                self._editor.rewrite_section_file(
                    path,
                    latex_directories,
                    rename_map,
                    edit=self._delete_merged_flavors(rename_map),
                )
            self._editor.rewrite_deck_files(rename_map)

        return merges

    @staticmethod
    def _delete_merged_flavors(rename_map: RenameMap) -> SectionEdit:
        def edit(data: Any, unresolved_section: UnresolvedPath) -> bool:
            renames = rename_map.get(unresolved_section)
            if not renames:
                return False
            flavors = data["flavors"]
            changed = False
            for i in reversed(range(len(flavors))):
                if flavors[i].get("name") in renames:
                    del flavors[i]
                    changed = True
            return changed

        return edit

    @staticmethod
    def _find_duplicates(
        flavors: list[FlavorDefinition],
    ) -> dict[FlavorName, FlavorName]:
        seen: dict[tuple[object, ...], FlavorName] = {}
        renames: dict[FlavorName, FlavorName] = {}
        for flavor in flavors:
            key = FlavorsMerger._flavor_key(flavor)
            if key in seen:
                renames[flavor.name] = seen[key]
            else:
                seen[key] = flavor.name
        return renames

    @staticmethod
    def _flavor_key(flavor: FlavorDefinition) -> tuple[object, ...]:
        return (
            flavor.title,
            tuple(
                (
                    str(include.path),
                    include.title,
                    include.flavor if isinstance(include, SectionInclude) else None,
                )
                for include in flavor.includes
            ),
        )

    @staticmethod
    def _group_by_kept(
        renames: Mapping[FlavorName, FlavorName],
    ) -> dict[FlavorName, list[FlavorName]]:
        grouped: dict[FlavorName, list[FlavorName]] = {}
        for removed, kept in renames.items():
            grouped.setdefault(kept, []).append(removed)
        return grouped
