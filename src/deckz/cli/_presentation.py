"""Terminal rendering of what the core reports: parse error trees and progress.

The core (`components/`, `pipelines.py`, ...) never draws on the terminal \
itself: it raises errors carrying data and reports progress through a \
[`ProgressReporterProtocol`][deckz.components.protocols.ProgressReporterProtocol]. \
This module is where the CLI turns those into rich widgets.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import PurePath

from rich.console import Console
from rich.progress import BarColumn, Progress
from rich.tree import Tree

from ..components.protocols import ProgressReporterProtocol
from ..models import Deck, File, NodeVisitor, Part, PartName, Section, UnresolvedPath


class RichProgress(ProgressReporterProtocol):
    @contextmanager
    def track(self, description: str, total: int) -> Iterator[Callable[[], None]]:
        with Progress(
            "[progress.description]{task.description}",
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
        ) as progress:
            task_id = progress.add_task(description, total=total)
            yield lambda: progress.update(task_id, advance=1)


def render_parse_errors(deck: Deck) -> None:
    """Print the part of `deck`'s tree leading to its parsing errors, on stderr."""
    tree = RichTreeVisitor().process(deck)
    if tree is not None:
        Console(stderr=True).print(tree)


class RichTreeVisitor(NodeVisitor[[UnresolvedPath], tuple[Tree | None, bool]]):
    def __init__(self, only_errors: bool = True) -> None:
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
            child_tree, child_error = child.accept(self, UnresolvedPath(PurePath()))
            error = error or child_error
            if child_tree is not None:
                children_trees.append(child_tree)

        if self._only_errors and not error:
            return None

        tree = Tree(part_name)
        tree.children.extend(children_trees)
        return tree

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
        for child in section.nodes:
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
