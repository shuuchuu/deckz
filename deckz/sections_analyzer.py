from collections.abc import Iterable, Iterator
from multiprocessing import Pool
from pathlib import Path, PurePath
from re import VERBOSE
from re import compile as re_compile

from yaml import safe_load

from .configuring.paths import Paths
from .deck_building import DeckBuilder
from .models.deck import Deck
from .models.definitions import SectionDefinition
from .models.scalars import ResolvedPath, UnresolvedPath
from .processing.section_dependencies import SectionDependenciesProcessor
from .processing.sections_usage import SectionsUsageProcessor


class SectionsAnalyzer:
    def __init__(self, git_dir: Path, shared_dir: Path, shared_latex_dir: Path) -> None:
        self._git_dir = git_dir
        self._shared_dir = shared_dir
        self._shared_latex_dir = shared_latex_dir

    def unused_flavors(self) -> dict[UnresolvedPath, set[str]]:
        unused_flavors = {p: set(d.flavors) for p, d in self._shared_sections.items()}
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
    ) -> dict[Path, set[str]]:
        section_path = UnresolvedPath(PurePath(section))
        using: dict[Path, set[str]] = {}
        for deck_path, section_stats in self._sections_usage.items():
            for part_name, section_flavors in section_stats.items():
                for path, flavors in section_flavors.items():
                    if path == section_path and (flavor is None or flavor in flavors):
                        if deck_path not in using:
                            using[deck_path] = set()
                        using[deck_path].add(part_name)
        return using

    def sections_unlicensed_images(self) -> dict[UnresolvedPath, frozenset[Path]]:
        return {
            s: frozenset(
                i for i in self._section_images(d) if not self._is_image_licensed(i)
            )
            for s, d in self._section_dependencies.items()
        }

    def _build_deck(self, targets_path: Path) -> tuple[Path, Deck]:
        paths = Paths.from_defaults(targets_path.parent)
        return (
            targets_path.parent.relative_to(self._git_dir),
            DeckBuilder(paths.local_latex_dir, paths.shared_latex_dir).from_targets(
                paths.deck_config, targets_path
            ),
        )

    @property
    def _decks(self) -> dict[Path, Deck]:
        if not hasattr(self, "__decks"):
            with Pool() as pool:
                self.__decks = dict(
                    pool.map(self._build_deck, self._git_dir.rglob("targets.yml"))
                )
        return self.__decks

    @property
    def _shared_sections(self) -> dict[UnresolvedPath, SectionDefinition]:
        if not hasattr(self, "__shared_sections"):
            self.__shared_sections = {}
            for path in self._shared_latex_dir.rglob("*.yml"):
                content = safe_load(path.read_text(encoding="utf8"))
                self.__shared_sections[
                    UnresolvedPath(path.parent.relative_to(self._shared_latex_dir))
                ] = SectionDefinition.model_validate(content)
        return self.__shared_sections

    @property
    def _sections_usage(self) -> dict[Path, dict[str, dict[UnresolvedPath, set[str]]]]:
        """Compute sections usage over all decks.

        Returns:
            Nested dictionaries: deck path -> part name -> section path -> flavor.
        """
        if not hasattr(self, "__sections_usage"):
            section_stats_processor = SectionsUsageProcessor(self._shared_latex_dir)
            self.__sections_usage = {
                deck_path: section_stats_processor.process(deck)
                for deck_path, deck in self._decks.items()
            }
        return self.__sections_usage

    @property
    def _section_dependencies(self) -> dict[UnresolvedPath, set[ResolvedPath]]:
        if not hasattr(self, "__section_dependencies"):
            section_dependencies_processor = SectionDependenciesProcessor()
            self.__section_dependencies: dict[UnresolvedPath, set[ResolvedPath]] = {}
            for deck in self._decks.values():
                section_dependencies = section_dependencies_processor.process(deck)
                for path, deps in section_dependencies.items():
                    if path not in self.__section_dependencies:
                        self.__section_dependencies[path] = set()
                    self.__section_dependencies[path].update(deps)
        return self.__section_dependencies

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
            for match in SectionsAnalyzer._pattern.finditer(
                path.read_text(encoding="utf8")
            ):
                if match is not None:
                    yield self._shared_dir / match.group(1)

    def _is_image_licensed(self, path: Path) -> bool:
        metadata_path = path.with_suffix(".yml")
        if not metadata_path.exists():
            return False
        return "license" in safe_load(metadata_path.read_text(encoding="utf8"))
