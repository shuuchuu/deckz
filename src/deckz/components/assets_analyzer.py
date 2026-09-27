from collections.abc import Iterable, Iterator, MutableMapping, MutableSet
from functools import cached_property
from pathlib import Path, PurePath
from typing import cast, get_args

from ..models import (
    Deck,
    File,
    Lang,
    NodeVisitor,
    Part,
    Section,
    UnresolvedPath,
)
from ..utils import all_decks, load_yaml
from .deck_builder import DependencyRef, variables_fingerprint
from .protocols import AssetsAnalyzerProtocol, RendererProtocol


class AssetsAnalyzer(AssetsAnalyzerProtocol):
    def __init__(
        self, assets_dir: Path, git_dir: Path, renderer: RendererProtocol
    ) -> None:
        self._assets_dir = assets_dir
        self._git_dir = git_dir
        self._renderer = renderer

    def sections_unlicensed_images(self) -> dict[UnresolvedPath, frozenset[Path]]:
        return {
            s: frozenset(
                i for i in self._section_assets(d) if not self._is_image_licensed(i)
            )
            for s, d in self._section_dependencies.items()
        }

    @cached_property
    def _decks(self) -> list[Deck]:
        # en decks can reference assets their fr counterparts don't.
        return [
            deck
            for lang in get_args(Lang)
            for deck in all_decks(self._git_dir, lang).values()
        ]

    @property
    def _section_dependencies(self) -> dict[UnresolvedPath, set[DependencyRef]]:
        section_dependencies_processor = _SectionDependenciesNodeVisitor()
        result: dict[UnresolvedPath, set[DependencyRef]] = {}
        for deck in self._decks:
            section_dependencies = section_dependencies_processor.process(deck)
            for path, deps in section_dependencies.items():
                if path not in result:
                    result[path] = set()
                result[path].update(deps)
        return result

    def _section_assets(self, dependencies: Iterable[DependencyRef]) -> Iterator[Path]:
        for dependency in dependencies:
            _, assets_usage = self._renderer.render_to_str(
                dependency.resolved_path, variables=dependency.variables
            )
            for asset in assets_usage:
                yield self._assets_dir / asset

    def _is_image_licensed(self, path: Path) -> bool:
        metadata_path = path.with_suffix(".yml")
        if not metadata_path.exists():
            return False
        return "license" in load_yaml(metadata_path)


class _SectionDependenciesNodeVisitor(
    NodeVisitor[
        [MutableMapping[UnresolvedPath, MutableSet[DependencyRef]], UnresolvedPath],
        None,
    ]
):
    def process(self, deck: Deck) -> dict[UnresolvedPath, set[DependencyRef]]:
        dependencies: dict[UnresolvedPath, set[DependencyRef]] = {}
        for part in deck.parts.values():
            self._process_part(
                part,
                cast(
                    "MutableMapping[UnresolvedPath, MutableSet[DependencyRef]]",
                    dependencies,
                ),
            )
        return dependencies

    def _process_part(
        self,
        part: Part,
        dependencies: MutableMapping[UnresolvedPath, MutableSet[DependencyRef]],
    ) -> None:
        for node in part.nodes:
            node.accept(self, dependencies, UnresolvedPath(PurePath()))

    def visit_file(
        self,
        file: File,
        section_dependencies: MutableMapping[UnresolvedPath, MutableSet[DependencyRef]],
        base_unresolved_path: UnresolvedPath,
    ) -> None:
        if base_unresolved_path not in section_dependencies:
            section_dependencies[base_unresolved_path] = set()
        section_dependencies[base_unresolved_path].add(
            DependencyRef(
                file.resolved_path,
                variables_fingerprint(file.variables),
                file.variables,
            )
        )

    def visit_section(
        self,
        section: Section,
        section_dependencies: MutableMapping[UnresolvedPath, MutableSet[DependencyRef]],
        base_unresolved_path: UnresolvedPath,
    ) -> None:
        for node in section.nodes:
            node.accept(self, section_dependencies, section.unresolved_path)
