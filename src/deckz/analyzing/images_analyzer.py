from collections.abc import Iterable, Iterator
from functools import cached_property
from pathlib import Path
from re import VERBOSE
from re import compile as re_compile

from ..models.deck import Deck
from ..models.scalars import ResolvedPath, UnresolvedPath
from ..processing.section_dependencies import SectionDependenciesProcessor
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
        section_dependencies_processor = SectionDependenciesProcessor()
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
