from ...configuring.paths import Paths
from ..targets import Part as TargetsPart
from ..targets import Title
from ..tree_parsing import Deck, File, Part, Section

ContentSlide = str


class SlidesVisitor:
    def __init__(self, paths: Paths) -> None:
        self.parts: list[TargetsPart] = []
        self._paths = paths

    def visit_file(self, file: File, level: int) -> None:
        if file.title:
            self.parts[-1].sections.append(Title(file.title, level))
        if file.path.is_relative_to(self._paths.shared_dir):
            path = file.path.relative_to(self._paths.shared_dir)
        elif file.path.is_relative_to(self._paths.current_dir):
            path = file.path.relative_to(self._paths.current_dir)
        else:
            raise ValueError
        path = path.with_suffix("")
        self.parts[-1].sections.append(str(path))

    def visit_section(self, section: Section, level: int) -> None:
        if section.title:
            self.parts[-1].sections.append(Title(section.title, level))
        for node in section.children:
            node.accept(self, level + 1)

    def visit_part(self, part: Part) -> None:
        self.parts.append(TargetsPart(part.title, []))
        for node in part.nodes:
            node.accept(self, 0)


def build_targets_parts(deck: Deck, paths: Paths) -> list[TargetsPart]:
    visitor = SlidesVisitor(paths)
    for part in deck.parts:
        part.accept(visitor)

    return visitor.parts
