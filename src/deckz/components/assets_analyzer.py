from collections.abc import Iterator, MutableMapping, MutableSet
from functools import cached_property
from pathlib import Path, PurePath
from typing import cast, get_args

from ..models import (
    Deck,
    File,
    Lang,
    NodeVisitor,
    ParsedDeck,
    Part,
    ResolvedPath,
    Section,
    UnresolvedPath,
)
from ..utils import all_decks, load_yaml
from .protocols import AssetsAnalyzerProtocol, RendererProtocol


class AssetsAnalyzer(AssetsAnalyzerProtocol):
    def __init__(
        self, assets_dir: Path, git_dir: Path, renderer: RendererProtocol
    ) -> None:
        self._assets_dir = assets_dir
        self._git_dir = git_dir
        self._renderer = renderer

    def sections_unlicensed_images(self) -> dict[UnresolvedPath, frozenset[Path]]:
        assets: dict[UnresolvedPath, set[Path]] = {}
        for parsed in self._decks:
            for section, files in (
                _SectionDependenciesNodeVisitor().process(parsed.deck).items()
            ):
                assets.setdefault(section, set()).update(
                    self._section_assets(files, parsed)
                )
        return {
            s: frozenset(i for i in a if not self._is_image_licensed(i))
            for s, a in assets.items()
        }

    @cached_property
    def _decks(self) -> list[ParsedDeck]:
        # en decks can reference assets their fr counterparts don't.
        return [
            parsed
            for lang in get_args(Lang)
            for parsed in all_decks(self._git_dir, lang).values()
        ]

    def _section_assets(
        self, files: set[ResolvedPath], parsed: ParsedDeck
    ) -> Iterator[Path]:
        for file in files:
            _, assets_usage = self._renderer.render_to_str(
                file, variables=parsed.variables
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
        [MutableMapping[UnresolvedPath, MutableSet[ResolvedPath]], UnresolvedPath],
        None,
    ]
):
    def process(self, deck: Deck) -> dict[UnresolvedPath, set[ResolvedPath]]:
        dependencies: dict[UnresolvedPath, set[ResolvedPath]] = {}
        for part in deck.parts.values():
            self._process_part(
                part,
                cast(
                    "MutableMapping[UnresolvedPath, MutableSet[ResolvedPath]]",
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
        if file.resolved_path is None:
            return
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
