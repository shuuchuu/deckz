from collections.abc import MutableSequence

from ...configuring.paths import Paths
from ..targets import PartSlides, Title
from ..tree_parsing import Deck, File, Part, Section

Content = str
TitleOrContent = Title | Content


class SlidesVisitor:
    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    def visit_file(
        self, file: File, sections: MutableSequence[TitleOrContent], level: int
    ) -> None:
        if file.title:
            sections.append(Title(file.title, level))
        if file.path.is_relative_to(self._paths.shared_dir):
            path = file.path.relative_to(self._paths.shared_dir)
        elif file.path.is_relative_to(self._paths.current_dir):
            path = file.path.relative_to(self._paths.current_dir)
        else:
            raise ValueError
        path = path.with_suffix("")
        sections.append(str(path))

    def visit_section(
        self, section: Section, sections: MutableSequence[TitleOrContent], level: int
    ) -> None:
        if section.title:
            sections.append(Title(section.title, level))
        for node in section.children:
            node.accept(self, sections, level + 1)

    def process_part(self, part: Part) -> PartSlides:
        sections: list[TitleOrContent] = []
        for node in part.nodes:
            node.accept(self, sections, 0)
        return PartSlides(part.title, sections)

    def process_deck(self, deck: Deck) -> dict[str, PartSlides]:
        return {
            part_name: self.process_part(part) for part_name, part in deck.parts.items()
        }
