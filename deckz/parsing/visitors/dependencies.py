from ...configuring.paths import Paths
from ..targets import Dependencies
from ..tree_parsing import Deck, File, Part, Section


class DependenciesVisitor:
    def __init__(self) -> None:
        self.dependencies: Dependencies = Dependencies()

    def visit_file(self, file: File) -> None:
        if file.parsing_error is None:
            self.dependencies.used.add(file.path)
            if file.path in self.dependencies.unused:
                self.dependencies.unused.remove(file.path)
        else:
            self.dependencies.missing.add(str(file.logical_path))

    def visit_section(self, section: Section) -> None:
        for node in section.children:
            node.accept(self)

    def visit_part(self, part: Part) -> None:
        for node in part.nodes:
            node.accept(self)


def build_dependencies(deck: Deck, paths: Paths) -> Dependencies:
    visitor = DependenciesVisitor()
    visitor.dependencies.unused.update(paths.local_latex_dir.rglob("*.tex"))
    for part in deck.parts:
        part.accept(visitor)

    return visitor.dependencies
