from pathlib import Path

from rich.tree import Tree

from ..tree_parsing import Deck, File, Part, Section


class RichTreeVisitor:
    def visit_file(self, file: File, tree: Tree, base_path: Path) -> None:
        path = (
            file.logical_path.relative_to(base_path)
            if file.logical_path.is_relative_to(base_path)
            else file.logical_path
        )
        if file.parsing_error is not None:
            tree.add(f"[red]{path} ({file.parsing_error})[/]")
        else:
            tree.add(str(path))

    def visit_section(self, section: Section, tree: Tree, base_path: Path) -> None:
        path = (
            section.logical_path.relative_to(base_path)
            if section.logical_path.is_relative_to(base_path)
            else section.logical_path
        )
        if section.parsing_error is not None:
            section_tree = tree.add(
                f"[red]{path}@{section.flavor} ({section.parsing_error})[/]"
            )
        else:
            section_tree = tree.add(f"{path}@{section.flavor}")

        for node in section.children:
            node.accept(self, section_tree, section.logical_path)

    def visit_part(self, part: Part, tree: Tree) -> None:
        part_tree = tree.add(part.name)
        for node in part.nodes:
            node.accept(self, part_tree, Path("/"))


def build_tree(deck: Deck) -> Tree:
    tree = Tree(deck.acronym)
    visitor = RichTreeVisitor()
    for part in deck.parts:
        part.accept(visitor, tree)

    return tree
