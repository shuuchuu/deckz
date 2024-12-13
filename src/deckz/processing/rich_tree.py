from pathlib import PurePath

from rich.tree import Tree

from ..models.deck import Deck, File, Part, Section
from ..models.scalars import PartName, UnresolvedPath
from . import NodeVisitor, Processor


class RichTreeProcessor(Processor[Tree | None]):
    def __init__(self, only_errors: bool = True) -> None:
        self._node_visitor = _RichTreeVisitor(only_errors)
        self._only_errors = only_errors

    def process(self, deck: Deck) -> Tree | None:
        part_trees = []
        for part_name, part in deck.parts.items():
            part_tree = self._process_part(part_name, part)
            if part_tree is not None:
                part_trees.append(part_tree)

        if part_trees:
            tree = Tree(deck.name)
            tree.children.extend(part_trees)
            return tree
        return None

    def _process_part(self, part_name: PartName, part: Part) -> Tree | None:
        error = False
        children_trees = []
        for child in part.nodes:
            child_tree, child_error = child.accept(
                self._node_visitor, UnresolvedPath(PurePath())
            )
            error = error or child_error
            if child_tree is not None:
                children_trees.append(child_tree)

        if self._only_errors and not error:
            return None

        tree = Tree(part_name)
        tree.children.extend(children_trees)
        return tree


class _RichTreeVisitor(NodeVisitor[[UnresolvedPath], tuple[Tree | None, bool]]):
    def __init__(self, only_errors: bool = True) -> None:
        self._only_errors = only_errors

    def visit_file(
        self, file: File, base_path: UnresolvedPath
    ) -> tuple[Tree | None, bool]:
        if self._only_errors and file.parsing_error is None:
            return None, False
        path = (
            file.unresolved_path.relative_to(base_path)
            if file.unresolved_path.is_relative_to(base_path)
            else file.unresolved_path
        )
        if file.parsing_error is None:
            return Tree(str(path)), False
        return Tree(f"[red]{path} ({file.parsing_error})[/]"), True

    def visit_section(
        self, section: Section, base_path: UnresolvedPath
    ) -> tuple[Tree | None, bool]:
        error = section.parsing_error is not None
        children_trees = []
        for child in section.children:
            child_tree, child_error = child.accept(self, section.unresolved_path)
            error = error or child_error
            if child_tree is not None:
                children_trees.append(child_tree)

        if self._only_errors and not error:
            return None, False

        path = (
            section.unresolved_path.relative_to(base_path)
            if section.unresolved_path.is_relative_to(base_path)
            else section.unresolved_path
        )

        if section.parsing_error is not None:
            label = f"[red]{path}@{section.flavor} ({section.parsing_error})[/]"
        else:
            label = f"{path}@{section.flavor}"

        tree = Tree(label)
        tree.children.extend(children_trees)

        return tree, error
