from functools import cached_property
from pathlib import Path, PurePath

from ..models.deck import Deck
from ..models.definitions import SectionDefinition
from ..models.scalars import FlavorName, PartName, UnresolvedPath
from ..processing.sections_usage import SectionsUsageProcessor
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
        section_stats_processor = SectionsUsageProcessor(self._shared_latex_dir)
        return {
            deck_path: section_stats_processor.process(deck)
            for deck_path, deck in self._decks.items()
        }
