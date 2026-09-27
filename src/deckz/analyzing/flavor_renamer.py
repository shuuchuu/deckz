from pathlib import Path
from typing import Any

from ..exceptions import (
    FlavorAlreadyExistsError,
    FlavorNotFoundError,
    SectionNotFoundError,
)
from ..models import FlavorName, SectionDefinition, UnresolvedPath
from .flavor_files import FlavorFilesEditor, RenameMap, SectionEdit


class FlavorRenamer:
    """Rename a section's flavor and rewrite every reference to it."""

    def __init__(self, git_dir: Path, shared_content_dir: Path) -> None:
        self._editor = FlavorFilesEditor(git_dir, shared_content_dir)

    def rename(
        self,
        section: UnresolvedPath,
        old: FlavorName,
        new: FlavorName,
        *,
        dry_run: bool = False,
    ) -> bool:
        """Rename a flavor and, unless `dry_run`, rewrite its usages.

        Every reference to the flavor, in every deck and section of the \
        repository, is rewritten to use the new name instead.

        Args:
            section: Path of the section the flavor belongs to
            old: Current name of the flavor
            new: New name for the flavor
            dry_run: Only validate the rename, without applying it

        Returns:
            Whether there was anything to rename (always True unless `old == new`).

        Raises:
            FlavorNotFoundError: Raised if `section` has no flavor named `old`
            FlavorAlreadyExistsError: Raised if `section` already has a flavor \
                named `new`
        """
        if old == new:
            return False

        content_directories = self._editor.content_directories()
        definitions = self._editor.section_definitions(content_directories)
        section_path, definition = self._find_section(
            section, definitions, content_directories
        )

        names = {flavor.name for flavor in definition.flavors}
        if old not in names:
            msg = f"section {section} has no flavor named {old}"
            raise FlavorNotFoundError(msg)
        if new in names:
            msg = f"section {section} already has a flavor named {new}"
            raise FlavorAlreadyExistsError(msg)

        if dry_run:
            return True

        rename_map: RenameMap = {section: {old: new}}
        self._editor.rewrite_section_file(
            section_path,
            content_directories,
            rename_map,
            edit=self._rename_flavor(section, old, new),
        )
        for path in definitions:
            if path != section_path:
                self._editor.rewrite_section_file(path, content_directories, rename_map)
        self._editor.rewrite_deck_files(rename_map)

        return True

    def _find_section(
        self,
        section: UnresolvedPath,
        definitions: dict[Path, SectionDefinition],
        content_directories: list[Path],
    ) -> tuple[Path, SectionDefinition]:
        for path, definition in definitions.items():
            if self._editor.unresolved_path(path, content_directories) == section:
                return path, definition
        msg = f"section {section} not found"
        raise SectionNotFoundError(msg)

    @staticmethod
    def _rename_flavor(
        section: UnresolvedPath, old: FlavorName, new: FlavorName
    ) -> SectionEdit:
        def edit(data: Any, unresolved_section: UnresolvedPath) -> bool:
            if unresolved_section != section:
                return False
            changed = False
            for flavor in data["flavors"]:
                if flavor.get("name") == old:
                    flavor["name"] = new
                    changed = True
            return changed

        return edit
