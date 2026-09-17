from collections.abc import Callable, Mapping, MutableMapping
from os.path import normpath
from pathlib import Path, PurePath
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML

from ..models import FlavorName, SectionDefinition, UnresolvedPath
from ..utils import latex_dirs, load_yaml, section_files

RenameMap = Mapping[UnresolvedPath, Mapping[FlavorName, FlavorName]]
"""For each section, the flavor names to rewrite references of, to their new name."""

SectionEdit = Callable[[Any, UnresolvedPath], bool]
"""Mutate a loaded section's yaml data (a ruamel `CommentedMap`) in place. Returns \
whether it was changed."""


class FlavorFilesEditor:
    """Shared machinery to find and rewrite flavor references across a repo.

    A flavor is referenced by its section's path and its own name, in the \
    `includes` of decks' parts and of other sections' flavors, using the \
    `$path/to/section@flavor` syntax. This class locates every section \
    definition of a repo, and can rewrite every one of those references, \
    wherever it is defined, to point to a new flavor name instead.
    """

    def __init__(self, git_dir: Path, shared_latex_dir: Path) -> None:
        self._git_dir = git_dir
        self._shared_latex_dir = shared_latex_dir
        self._yaml = YAML()
        self._yaml.indent(mapping=2, sequence=4, offset=2)

    def latex_directories(self) -> list[Path]:
        return list(latex_dirs(self._git_dir, self._shared_latex_dir))

    def section_definitions(
        self, latex_directories: list[Path]
    ) -> dict[Path, SectionDefinition]:
        return {
            path: definition
            for path in section_files(iter(latex_directories))
            if (definition := self._as_section_definition(path)) is not None
        }

    @staticmethod
    def _as_section_definition(path: Path) -> SectionDefinition | None:
        # Latex directories can also hold unrelated yaml sidecar files (e.g. a file
        # include's title metadata), which aren't section definitions.
        try:
            return SectionDefinition.model_validate(load_yaml(path))
        except ValidationError:
            return None

    @staticmethod
    def unresolved_path(path: Path, latex_directories: list[Path]) -> UnresolvedPath:
        for latex_dir in latex_directories:
            if path.is_relative_to(latex_dir):
                return UnresolvedPath(path.parent.relative_to(latex_dir))
        msg = f"{path} is not located under a known latex directory"
        raise ValueError(msg)

    def rewrite_section_file(
        self,
        path: Path,
        latex_directories: list[Path],
        rename_map: RenameMap,
        *,
        edit: SectionEdit | None = None,
    ) -> None:
        unresolved_section = self.unresolved_path(path, latex_directories)
        with path.open(encoding="utf8") as fh:
            data = self._yaml.load(fh)

        changed = edit(data, unresolved_section) if edit is not None else False

        for flavor in data.get("flavors", ()):
            changed = (
                self._rewrite_includes(
                    flavor.get("includes", ()), rename_map, base=unresolved_section
                )
                or changed
            )

        if changed:
            with path.open("w", encoding="utf8") as fh:
                self._yaml.dump(data, fh)

    def rewrite_deck_files(self, rename_map: RenameMap) -> None:
        for deck_definition_path in self._git_dir.rglob("deck.yml"):
            self._rewrite_deck_file(deck_definition_path, rename_map)

    def _rewrite_deck_file(self, path: Path, rename_map: RenameMap) -> None:
        with path.open(encoding="utf8") as fh:
            data = self._yaml.load(fh)

        changed = False
        for part in data.get("parts", ()):
            changed = (
                self._rewrite_includes(
                    part.get("sections", ()),
                    rename_map,
                    base=UnresolvedPath(PurePath()),
                )
                or changed
            )

        if changed:
            with path.open("w", encoding="utf8") as fh:
                self._yaml.dump(data, fh)

    def _rewrite_includes(
        self,
        includes: list[object],
        rename_map: RenameMap,
        *,
        base: UnresolvedPath,
    ) -> bool:
        changed = False
        for i, include in enumerate(includes):
            parsed = self._parse_reference(include)
            if parsed is None:
                continue
            path_str, flavor = parsed
            target = self._resolve(base, path_str)
            renames = rename_map.get(target)
            if renames is None or flavor not in renames:
                continue
            new_key = f"${path_str}@{renames[flavor]}"
            if isinstance(include, str):
                includes[i] = new_key
            else:
                assert isinstance(include, MutableMapping)
                old_key = next(iter(include))
                title = include[old_key]
                del include[old_key]
                include[new_key] = title
            changed = True
        return changed

    @staticmethod
    def _parse_reference(include: object) -> tuple[str, FlavorName] | None:
        if isinstance(include, str):
            key = include
        elif isinstance(include, Mapping) and len(include) == 1:
            key = next(iter(include))
        else:
            return None
        if not key.startswith("$"):
            return None
        path, _, flavor = key[1:].partition("@")
        if not flavor:
            return None
        return path, FlavorName(flavor)

    @staticmethod
    def _resolve(base: UnresolvedPath, path_str: str) -> UnresolvedPath:
        include_path = PurePath(path_str)
        if include_path.root:
            return UnresolvedPath(include_path.relative_to("/"))
        return UnresolvedPath(PurePath(normpath(base / include_path)))
