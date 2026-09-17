from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from os.path import normpath
from pathlib import Path, PurePath

from pydantic import ValidationError
from ruamel.yaml import YAML

from ..models import (
    FlavorDefinition,
    FlavorName,
    SectionDefinition,
    SectionInclude,
    UnresolvedPath,
)
from ..utils import latex_dirs, load_yaml, section_files


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
        self._git_dir = git_dir
        self._shared_latex_dir = shared_latex_dir
        self._yaml = YAML()
        self._yaml.indent(mapping=2, sequence=4, offset=2)

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
        latex_directories = list(latex_dirs(self._git_dir, self._shared_latex_dir))
        definitions = {
            path: definition
            for path in section_files(iter(latex_directories))
            if (definition := self._as_section_definition(path)) is not None
        }
        section_paths = list(definitions)

        merge_map: dict[UnresolvedPath, dict[FlavorName, FlavorName]] = {}
        merges: list[FlavorsMerge] = []
        for section_path, definition in definitions.items():
            unresolved_section = self._unresolved_path(section_path, latex_directories)
            renames = self._find_duplicates(definition.flavors)
            if not renames:
                continue
            merge_map[unresolved_section] = renames
            for kept, removed in self._group_by_kept(renames).items():
                merges.append(
                    FlavorsMerge(unresolved_section, kept, frozenset(removed))
                )

        if not dry_run and merge_map:
            for section_path in section_paths:
                self._rewrite_section_file(section_path, latex_directories, merge_map)
            for deck_definition_path in self._git_dir.rglob("deck.yml"):
                self._rewrite_references_file(
                    deck_definition_path, UnresolvedPath(PurePath()), merge_map
                )

        return merges

    @staticmethod
    def _as_section_definition(path: Path) -> SectionDefinition | None:
        # Latex directories can also hold unrelated yaml sidecar files (e.g. a file
        # include's title metadata), which aren't section definitions.
        try:
            return SectionDefinition.model_validate(load_yaml(path))
        except ValidationError:
            return None

    @staticmethod
    def _unresolved_path(path: Path, latex_directories: list[Path]) -> UnresolvedPath:
        for latex_dir in latex_directories:
            if path.is_relative_to(latex_dir):
                return UnresolvedPath(path.parent.relative_to(latex_dir))
        msg = f"{path} is not located under a known latex directory"
        raise ValueError(msg)

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

    def _rewrite_section_file(
        self,
        path: Path,
        latex_directories: list[Path],
        merge_map: Mapping[UnresolvedPath, Mapping[FlavorName, FlavorName]],
    ) -> None:
        unresolved_section = self._unresolved_path(path, latex_directories)
        with path.open(encoding="utf8") as fh:
            data = self._yaml.load(fh)

        changed = False
        renames = merge_map.get(unresolved_section)
        if renames:
            flavors = data["flavors"]
            for i in reversed(range(len(flavors))):
                if flavors[i].get("name") in renames:
                    del flavors[i]
                    changed = True

        for flavor in data.get("flavors", ()):
            changed = (
                self._rewrite_includes(
                    flavor.get("includes", ()), merge_map, base=unresolved_section
                )
                or changed
            )

        if changed:
            with path.open("w", encoding="utf8") as fh:
                self._yaml.dump(data, fh)

    def _rewrite_references_file(
        self,
        path: Path,
        base: UnresolvedPath,
        merge_map: Mapping[UnresolvedPath, Mapping[FlavorName, FlavorName]],
    ) -> None:
        with path.open(encoding="utf8") as fh:
            data = self._yaml.load(fh)

        changed = False
        for part in data.get("parts", ()):
            changed = (
                self._rewrite_includes(part.get("sections", ()), merge_map, base=base)
                or changed
            )

        if changed:
            with path.open("w", encoding="utf8") as fh:
                self._yaml.dump(data, fh)

    def _rewrite_includes(
        self,
        includes: list[object],
        merge_map: Mapping[UnresolvedPath, Mapping[FlavorName, FlavorName]],
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
            renames = merge_map.get(target)
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
