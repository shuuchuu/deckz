from pathlib import Path

from yaml import safe_load

from .configuring.paths import Paths
from .deck_building import DeckBuilder
from .models import Deck, SectionDefinition
from .processing.section_stats import SectionStatsProcessor


class SectionDeps:
    def __init__(self, git_dir: Path, shared_latex_dir: Path) -> None:
        self._git_dir = git_dir
        self._shared_latex_dir = shared_latex_dir

    def unused_flavors(self) -> dict[Path, set[str]]:
        unused_flavors = {p: set(d.flavors) for p, d in self._shared_sections.items()}
        for section_stats in self._section_stats.values():
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
        section_path = Path(section)
        using: dict[Path, set[str]] = {}
        for deck_path, section_stats in self._section_stats.items():
            for part_name, section_flavors in section_stats.items():
                for path, flavors in section_flavors.items():
                    if path == section_path and (flavor is None or flavor in flavors):
                        if deck_path not in using:
                            using[deck_path] = set()
                        using[deck_path].add(part_name)
        return using

    @property
    def _decks(self) -> dict[Path, Deck]:
        if not hasattr(self, "__decks"):
            self.__decks = {}
            for targets_path in self._git_dir.rglob("targets.yml"):
                paths = Paths.from_defaults(targets_path.parent)
                self.__decks[targets_path.parent.relative_to(self._git_dir)] = (
                    DeckBuilder(
                        paths.local_latex_dir, paths.shared_latex_dir
                    ).from_targets(paths.deck_config, targets_path)
                )
        return self.__decks

    @property
    def _shared_sections(self) -> dict[Path, SectionDefinition]:
        if not hasattr(self, "__shared_sections"):
            self.__shared_sections = {}
            for path in self._shared_latex_dir.rglob("*.yml"):
                content = safe_load(path.read_text(encoding="utf8"))
                self.__shared_sections[
                    path.parent.relative_to(self._shared_latex_dir)
                ] = SectionDefinition.model_validate(content)
        return self.__shared_sections

    @property
    def _section_stats(self) -> dict[Path, dict[str, dict[Path, set[str]]]]:
        if not hasattr(self, "__section_stats"):
            section_stats_processor = SectionStatsProcessor(self._shared_latex_dir)
            self.__section_stats = {
                deck_path: section_stats_processor.process(deck)
                for deck_path, deck in self._decks.items()
            }
        return self.__section_stats
