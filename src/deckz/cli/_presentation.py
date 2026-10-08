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
from ..models import (
    Deck,
    File,
    NodeVisitor,
    Part,
    PartName,
    Section,
    UnresolvedPath,
    lang_dir,
)

if TYPE_CHECKING:
    from ..components.deck_builder import PlannedCompile
    from ..configuring.settings import DeckSettings
    from ..labs.gpu import GpuStatus, RunReport
    from ..models import Lang
    from ..pipelines import BuildTarget, OutputKinds


class RichProgress(ProgressReporterProtocol):
    def __init__(self) -> None:
        self._progress: Progress | None = None

    @contextmanager
    def track(self, description: str, total: int) -> Iterator[Callable[[], None]]:
        # A task tracked within another (a deck's compilations within `run
        # decks`) is one more bar of the same display, not a display of its
        # own: two live displays at once overwrite each other, and flicker.
        if self._progress is not None:
            progress = self._progress
            task_id = progress.add_task(description, total=total)
            try:
                yield lambda: progress.update(task_id, advance=1)
            finally:
                progress.remove_task(task_id)
            return
        with Progress(
            "[progress.description]{task.description}",
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            console=Console(stderr=True),
        ) as progress:
            self._progress = progress
            try:
                task_id = progress.add_task(description, total=total)
                yield lambda: progress.update(task_id, advance=1)
            finally:
                self._progress = None


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


def show_output_dirs(
    settings: "DeckSettings",
    langs: "Sequence[Lang]",
    outputs: "OutputKinds",
    *,
    open_dir: bool,
) -> None:
    """Log where a `run file`/`run section` preview writes, and maybe open it.

    Args:
        settings: The preview's settings.
        langs: The languages the preview builds, each written apart.
        outputs: What the preview builds.
        open_dir: Open the first output directory: an HTML one when only \
            HTML is built.
    """
    from logging import getLogger

    logger = getLogger(__name__)
    pdfs = outputs.handout or outputs.presentation or outputs.print
    bases = [settings.paths.pdf_dir] if pdfs or not outputs.html else []
    if outputs.html:
        bases.append(settings.paths.html_dir)
    dirs = [lang_dir(base, lang) for base in bases for lang in langs]
    for directory in dirs:
        logger.info(
            f"Output directory located at [link=file://{directory}]{directory}[/link]",
            extra={"markup": True},
        )
    if open_dir:
        open_path(dirs[0])


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


def print_plan_of(targets: "Sequence[BuildTarget]", outputs: "OutputKinds") -> None:
    """Print what building `targets` would do, for a `run` command's `--dry-run`.

    Paths are printed relative to the repository root.
    """
    from ..pipelines import plan, stale_pdfs

    if not targets:
        return
    planned = plan(targets, outputs)
    removed = (
        stale_pdfs(targets, (item.output_path for item in planned))
        if outputs.sync
        else []
    )
    print_plan(planned, targets[0].settings.paths.git_dir, removed)


def print_plan(
    planned: Iterable["PlannedCompile"],
    relative_to: Path,
    removed: Iterable[Path] = (),
) -> None:
    """Print what a build would do, one output per line, then its changed fragments.

    Args:
        planned: The build's plan.
        relative_to: Directory paths are printed relative to, when inside it.
        removed: PDFs the build would then remove, printed last.
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
    for path in removed:
        print(f"{display(path)}: remove (not produced by this build)")


def print_gpu_status(status: "GpuStatus") -> None:
    """Print a `deckz labs gpu status` as a table, for a person."""
    from rich.table import Table

    console = Console(highlight=False)
    instance = status.instance
    if instance is None:
        console.print("No machine rented.")
        return
    console.print(
        f"Machine: [bold]{instance.status}[/bold], {instance.gpu or '?'},"
        f" ${instance.price:.3f}/h"
        + (f" ({instance.message})" if instance.message else "")
    )
    if not status.queue:
        return
    table = Table("Notebook", "State", "Exit", "Time")
    for entry in status.queue:
        color = {"done": "green", "running": "yellow"}.get(entry.state, "dim")
        if entry.state == "done" and entry.exit_code:
            color = "red"
        table.add_row(
            entry.name,
            f"[{color}]{entry.state}[/{color}]",
            "" if entry.exit_code is None else str(entry.exit_code),
            "" if entry.seconds is None else f"{entry.seconds // 60} min",
        )
    console.print(table)


def print_gpu_reports(reports: Iterable["RunReport"]) -> None:
    """Print `deckz labs gpu report`'s runs as a table, for a person."""
    from rich.table import Table

    table = Table("Notebook", "Exit", "Time", "Peak RAM", "Cells", "Raised")
    for run in reports:
        table.add_row(
            run.path.name,
            "?" if run.exit_code is None else str(run.exit_code),
            "?" if run.seconds is None else f"{run.seconds / 60:.1f} min",
            "?" if run.peak_ram_gib is None else f"{run.peak_ram_gib:.1f} GiB",
            f"{run.cells_ran}/{run.code_cells}",
            "\n".join(f"[{e.index}] {e.name}" for e in run.errors)
            or "[green]none[/green]",
        )
    Console(highlight=False).print(table)
