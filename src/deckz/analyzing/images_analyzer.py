from collections.abc import Iterable, Iterator, MutableMapping, MutableSet
from functools import cached_property
from pathlib import Path, PurePath
from re import VERBOSE
from re import compile as re_compile
from typing import cast

from ..models import (
    Deck,
    File,
    NodeVisitor,
    Part,
    ResolvedPath,
    Section,
    UnresolvedPath,
)
from ..utils import all_decks, load_yaml


class ImagesAnalyzer:
    def __init__(self, shared_dir: Path, git_dir: Path) -> None:
        self._shared_dir = shared_dir
        self._git_dir = git_dir

    def sections_unlicensed_images(self) -> dict[UnresolvedPath, frozenset[Path]]:
        return {
            s: frozenset(
                i for i in self._section_images(d) if not self._is_image_licensed(i)
            )
            for s, d in self._section_dependencies.items()
        }

    @cached_property
    def _decks(self) -> dict[Path, Deck]:
        return all_decks(self._git_dir)

    @property
    def _section_dependencies(self) -> dict[UnresolvedPath, set[ResolvedPath]]:
        section_dependencies_processor = _SectionDependenciesNodeVisitor()
        result: dict[UnresolvedPath, set[ResolvedPath]] = {}
        for deck in self._decks.values():
            section_dependencies = section_dependencies_processor.process(deck)
            for path, deps in section_dependencies.items():
                if path not in result:
                    result[path] = set()
                result[path].update(deps)
        return result

    _pattern = re_compile(
        r"""
        \\V{
            \s*
            "(.+?)"
            \s*
            \|
            \s*
            image
            \s*
            (?:\([^)]*\))?
            \s*
          }
        """,
        VERBOSE,
    )

    def _section_images(self, dependencies: Iterable[Path]) -> Iterator[Path]:
        for path in dependencies:
            for match in ImagesAnalyzer._pattern.finditer(
                path.read_text(encoding="utf8")
            ):
                if match is not None:
                    yield self._shared_dir / match.group(1)

    def _is_image_licensed(self, path: Path) -> bool:
        metadata_path = path.with_suffix(".yml")
        if not metadata_path.exists():
            return False
        return "license" in load_yaml(metadata_path)


class _SectionDependenciesNodeVisitor(
    NodeVisitor[
        [MutableMapping[UnresolvedPath, MutableSet[ResolvedPath]], UnresolvedPath], None
    ]
):
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
            node.accept(self, dependencies, UnresolvedPath(PurePath()))

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
