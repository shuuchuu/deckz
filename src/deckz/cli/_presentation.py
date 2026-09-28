"""Terminal rendering of what the core reports: parse error trees and progress.

The core (`components/`, `pipelines.py`, ...) never draws on the terminal \
itself: it raises errors carrying data and reports progress through a \
[`ProgressReporterProtocol`][deckz.components.protocols.ProgressReporterProtocol]. \
This module is where the CLI turns those into rich widgets.
"""

import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePath
from subprocess import DEVNULL, Popen
from typing import TYPE_CHECKING

from rich.console import Console
from rich.progress import BarColumn, Progress
from rich.tree import Tree

from ..components.protocols import ProgressReporterProtocol
from ..models import Deck, File, NodeVisitor, Part, PartName, Section, UnresolvedPath

if TYPE_CHECKING:
    from ..components.deck_builder import PlannedCompile
    from ..models import Lang
    from ..pipelines import BuildTarget, OutputKinds


class RichProgress(ProgressReporterProtocol):
    @contextmanager
    def track(self, description: str, total: int) -> Iterator[Callable[[], None]]:
        with Progress(
            "[progress.description]{task.description}",
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            console=Console(stderr=True),
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


def open_path(path: Path) -> None:
    """Open `path` with the desktop's default application, without waiting for it.

    Args:
        path: File or directory to open.
    """
    if sys.platform == "win32":
        from os import startfile  # ty: ignore[unresolved-import]

        startfile(path)
        return
    command = "open" if sys.platform == "darwin" else "xdg-open"
    Popen([command, str(path)], stdout=DEVNULL, stderr=DEVNULL, stdin=DEVNULL)


def print_json(data: object) -> None:
    """Print `data` to stdout as JSON, for a command's `--json`.

    Paths and other non-JSON values are printed as strings.
    """
    from json import dumps

    print(dumps(data, indent=2, default=str))


def deck_json(deck: Deck) -> dict[str, object]:
    """`deck`'s tree as JSON-ready data, for `deckz show tree --json`.

    Returns:
        The deck's name and parts, each part's nodes nested as in the deck.
    """
    visitor = _JsonNodeVisitor()
    return {
        "name": deck.name,
        "parts": [
            {
                "name": name,
                "title": part.title,
                "nodes": [node.accept(visitor) for node in part.nodes],
            }
            for name, part in deck.parts.items()
        ],
    }


class _JsonNodeVisitor(NodeVisitor[[], dict[str, object]]):
    def visit_file(self, file: File) -> dict[str, object]:
        return {
            "kind": "file",
            "path": file.unresolved_path.as_posix(),
            "resolved_path": file.resolved_path,
            "title": file.title,
            "error": file.parsing_error,
        }

    def visit_section(self, section: Section) -> dict[str, object]:
        return {
            "kind": "section",
            "path": section.unresolved_path.as_posix(),
            "flavor": section.flavor,
            "resolved_path": section.resolved_path,
            "title": section.title,
            "error": section.parsing_error,
            "nodes": [node.accept(self) for node in section.nodes],
        }


def print_plan_of(
    targets: "Sequence[BuildTarget]", lang: "Lang", outputs: "OutputKinds"
) -> None:
    """Print what building `targets` would do, for a `run` command's `--dry-run`.

    Paths are printed relative to the repository root.
    """
    from ..pipelines import plan

    if targets:
        print_plan(plan(targets, lang, outputs), targets[0].settings.paths.git_dir)


def print_plan(planned: Iterable["PlannedCompile"], relative_to: Path) -> None:
    """Print what a build would do, one PDF per line, then its changed fragments.

    Args:
        planned: The build's plan.
        relative_to: Directory paths are printed relative to, when inside it.
    """

    def display(path: Path) -> str:
        if path.is_relative_to(relative_to):
            return str(path.relative_to(relative_to))
        return str(path)

    for item in planned:
        if item.full_render:
            print(
                f"{display(item.output_path)}: render all {item.fragments} "
                "fragments (first build or Markdown converter changed)"
            )
            continue
        print(
            f"{display(item.output_path)}: render "
            f"{len(item.changed_fragments)} of {item.fragments} fragments"
        )
        for fragment in item.changed_fragments:
            print(f"  {display(fragment)}")
