from collections.abc import MutableSequence
from pathlib import Path

from ..models.deck import Deck, File, Part, Section
from ..models.scalars import PartName
from ..models.slides import PartSlides, Title, TitleOrContent
from . import NodeVisitor, Processor


class SlidesProcessor(Processor[dict[PartName, PartSlides]]):
    def __init__(self, shared_dir: Path, current_dir: Path) -> None:
        self._visitor = _SlidesNodeVisitor(
            shared_dir=shared_dir, current_dir=current_dir
        )

    def process(self, deck: Deck) -> dict[PartName, PartSlides]:
        return {
            part_name: self._process_part(part)
            for part_name, part in deck.parts.items()
        }

    def _process_part(self, part: Part) -> PartSlides:
        sections: list[TitleOrContent] = []
        for node in part.nodes:
            node.accept(self._visitor, sections, 0)
        return PartSlides(part.title, sections)


class _SlidesNodeVisitor(NodeVisitor[[MutableSequence[TitleOrContent], int], None]):
    def __init__(self, shared_dir: Path, current_dir: Path) -> None:
        self._shared_dir = shared_dir
        self._current_dir = current_dir

    def visit_file(
        self, file: File, sections: MutableSequence[TitleOrContent], level: int
    ) -> None:
        if file.title:
            sections.append(Title(file.title, level))
        if file.resolved_path.is_relative_to(self._shared_dir):
            path = file.resolved_path.relative_to(self._shared_dir)
        elif file.resolved_path.is_relative_to(self._current_dir):
            path = file.resolved_path.relative_to(self._current_dir)
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
