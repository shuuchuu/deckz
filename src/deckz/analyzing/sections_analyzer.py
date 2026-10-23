from collections.abc import Iterable, Mapping, MutableMapping, MutableSet
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, cast, get_args

from ..models import (
    Deck,
    File,
    FlavorName,
    Lang,
    Node,
    NodeVisitor,
    Part,
    PartName,
    ResolvedPath,
    Section,
    SectionDefinition,
    UnresolvedPath,
)
from ..utils import all_decks, content_dirs, content_files, load_yaml

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings


def frame_count(path: Path) -> int:
    """Count a Markdown file's frames: its level-1 headings, outside code blocks.

    Returns:
        The number of `# ` lines outside fenced code blocks, as a build \
        marks them (`frame_markers.frame_headings`).
    """
    from ..components.frame_markers import frame_headings

    return len(frame_headings(path.read_text(encoding="utf8")))


def ordered_files(nodes: Iterable[Node]) -> list[ResolvedPath]:
    """The files of `nodes`, recursively, in include order, each once.

    Returns:
        Their resolved paths; a node that didn't resolve is left out.
    """
    found: dict[ResolvedPath, None] = {}
    for node in nodes:
        if isinstance(node, Section):
            found.update(dict.fromkeys(ordered_files(node.nodes)))
        elif isinstance(node, File) and node.resolved_path is not None:
            found[node.resolved_path] = None
    return list(found)


@dataclass(frozen=True)
class FlavorUsage:
    files: dict[Path, int]
    """Its files (absolute, in include order, nested sections resolved, in \
    French), each with its frames."""
    dependents: dict[Path, set[PartName]]
    """The decks using it (relative to the repository), with their parts."""


class SectionsAnalyzer:
    def __init__(
        self, shared_content_dir: Path, git_dir: Path, file_extensions: Iterable[str]
    ) -> None:
        self._shared_content_dir = shared_content_dir
        self._git_dir = git_dir
        self._file_extensions = tuple(file_extensions)

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

    def unused_files(self) -> frozenset[Path]:
        return frozenset(
            path
            for content_dir in content_dirs(self._git_dir, self._shared_content_dir)
            for path in content_files(content_dir, self._file_extensions)
            if ResolvedPath(path.resolve()) not in self._used_files
        )

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

    def section_flavors(self, section: str) -> list[FlavorName]:
        """The flavors of a shared section, in its definition's order.

        Returns:
            Their names; none if there's no such section.
        """
        definition = self._shared_sections.get(UnresolvedPath(PurePath(section)))
        return [] if definition is None else [f.name for f in definition.flavors]

    def flavors_usage(
        self, settings: "GlobalSettings", section: str, flavor: str | None = None
    ) -> dict[FlavorName, FlavorUsage]:
        """Each flavor of a shared section: its files and the decks using it.

        Args:
            settings: The repository's settings, to resolve the flavors.
            section: The section's path relative to the shared content \
                directory.
            flavor: Only this flavor; every one if None.

        Returns:
            Each flavor's usage, in the section definition's order; nothing \
            for an unknown section or flavor.
        """
        from .sections_search import ordered_section_files

        return {
            name: FlavorUsage(
                {
                    Path(path): frame_count(Path(path))
                    for path in ordered_section_files(settings, section, name)
                },
                self.parts_using_flavor(section, name),
            )
            for name in self.section_flavors(section)
            if flavor is None or name == flavor
        }

    def deck_frames(self, decks: Iterable[Path]) -> dict[Path, int]:
        """Each deck's total frames, in French: its files' frames, summed.

        Args:
            decks: Deck directories relative to the repository, as \
                `parts_using_flavor` gives them.

        Returns:
            The total of each deck found, by deck.
        """
        totals = {}
        for deck_path in decks:
            if (deck := self._decks.get(deck_path)) is None:
                continue
            totals[deck_path] = sum(
                frame_count(Path(path))
                for part in deck.parts.values()
                for path in ordered_files(part.nodes)
            )
        return totals

    @cached_property
    def _decks(self) -> Mapping[Path, Deck]:
        return {path: parsed.deck for path, parsed in all_decks(self._git_dir).items()}

    @cached_property
    def _shared_sections(self) -> dict[UnresolvedPath, SectionDefinition]:
        result = {}
        for path in self._shared_content_dir.rglob("*.yml"):
            content = load_yaml(path)
            result[
                UnresolvedPath(path.parent.relative_to(self._shared_content_dir))
            ] = SectionDefinition.model_validate(content)
        return result

    @cached_property
    def _sections_usage(
        self,
    ) -> dict[Path, dict[PartName, dict[UnresolvedPath, set[FlavorName]]]]:
        """Compute sections usage over all decks.

        Returns:
            Nested dictionaries: deck path -> part name -> section path -> flavor.
        """
        section_stats_processor = _SectionsUsageNodeVisitor(self._shared_content_dir)
        return {
            deck_path: section_stats_processor.process(deck)
            for deck_path, deck in self._decks.items()
        }

    @cached_property
    def _used_files(self) -> frozenset[ResolvedPath]:
        """Files some deck resolves to, in fr or in en."""
        files_usage_processor = _FilesUsageNodeVisitor()
        used: set[ResolvedPath] = set()
        for lang in get_args(Lang):
            for parsed in all_decks(self._git_dir, lang).values():
                used.update(files_usage_processor.process(parsed.deck))
        return frozenset(used)


class _SectionsUsageNodeVisitor(
    NodeVisitor[[MutableMapping[UnresolvedPath, MutableSet[FlavorName]]], None]
):
    def __init__(self, shared_content_dir: Path) -> None:
        self._shared_content_dir = shared_content_dir

    def process(
        self, deck: Deck
    ) -> dict[PartName, dict[UnresolvedPath, set[FlavorName]]]:
        return {
            part_name: self._process_part(part)
            for part_name, part in deck.parts.items()
        }

    def _process_part(self, part: Part) -> dict[UnresolvedPath, set[FlavorName]]:
        section_stats: dict[UnresolvedPath, set[FlavorName]] = {}
        for node in part.nodes:
            node.accept(
                self,
                # Not sure why we need a cast here :/
                cast(
                    "MutableMapping[UnresolvedPath, MutableSet[FlavorName]]",
                    section_stats,
                ),
            )
        return section_stats

    def visit_file(
        self,
        file: File,
        section_stats: MutableMapping[UnresolvedPath, MutableSet[FlavorName]],
    ) -> None:
        pass

    def visit_section(
        self,
        section: Section,
        section_stats: MutableMapping[UnresolvedPath, MutableSet[FlavorName]],
    ) -> None:
        if section.resolved_path is not None and section.resolved_path.is_relative_to(
            self._shared_content_dir
        ):
            if section.unresolved_path not in section_stats:
                section_stats[section.unresolved_path] = set()
            section_stats[section.unresolved_path].add(section.flavor)
        for node in section.nodes:
            node.accept(self, section_stats)


class _FilesUsageNodeVisitor(NodeVisitor[[MutableSet[ResolvedPath]], None]):
    def process(self, deck: Deck) -> set[ResolvedPath]:
        used: set[ResolvedPath] = set()
        for part in deck.parts.values():
            for node in part.nodes:
                node.accept(self, cast("MutableSet[ResolvedPath]", used))
        return used

    def visit_file(self, file: File, used: MutableSet[ResolvedPath]) -> None:
        if file.resolved_path is not None:
            used.add(file.resolved_path)

    def visit_section(self, section: Section, used: MutableSet[ResolvedPath]) -> None:
        for node in section.nodes:
            node.accept(self, used)
