from pathlib import Path
from typing import TYPE_CHECKING

from . import app
from ._groups import CONTENT

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from rich.console import Console

    from ..models import UnresolvedPath


@app.command(group=CONTENT)
def deps(
    section: str | None = None,
    flavor: str | None = None,
    /,
    *,
    unused: bool = True,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Display information about shared sections, flavors and content files usage.

    The content files no deck includes (shared or local to a deck, fr or en/)
    are listed, never deleted: they can be kept on purpose, as material for
    decks to come.

    Args:
        section: Restrict the output to only this section
        flavor: Restrict the output further to only this section
        unused: Display unused flavors and content files
        json: Print one JSON object instead, with "unused_flavors"
            (section to flavor names), "unused_files" (path from the
            repository root to its number of frames) and, given SECTION,
            "dependents" (deck to part names)
        workdir: Path to move into before running the command

    """
    from rich.console import Console

    from ..analyzing.sections_analyzer import SectionsAnalyzer
    from ..configuring.settings import GlobalSettings

    if not unused and section is None:
        return

    console = Console()

    settings = GlobalSettings.from_yaml(workdir)
    sections_analyzer = SectionsAnalyzer(
        settings.paths.content_dir,
        settings.paths.git_dir,
        settings.file_extensions,
    )

    if json:
        from ._presentation import print_json

        report: dict[str, object] = {}
        if unused:
            report["unused_flavors"] = {
                str(path): sorted(flavors)
                for path, flavors in sections_analyzer.unused_flavors().items()
            }
            report["unused_files"] = {
                str(path.relative_to(settings.paths.git_dir)): _frame_count(path)
                for path in sorted(sections_analyzer.unused_files())
            }
        if section is not None:
            report["dependents"] = {
                str(deck): sorted(parts)
                for deck, parts in sections_analyzer.parts_using_flavor(
                    section, flavor
                ).items()
            }
        print_json(report)
        return

    if unused:
        with Console(stderr=True).status("Processing decks"):
            _print_unused_report(sections_analyzer.unused_flavors(), console)
        console.print()
        with Console(stderr=True).status("Finding unused content files"):
            _print_unused_files_report(
                sections_analyzer.unused_files(), settings.paths.git_dir, console
            )

    if section is not None:
        if unused:
            console.print()
        with Console(stderr=True).status("Processing decks"):
            _print_section_report(
                section,
                flavor,
                sections_analyzer.parts_using_flavor(section, flavor),
                console,
            )


def _print_unused_report(
    unused_flavors: "Mapping[UnresolvedPath, Iterable[str]]", console: "Console"
) -> None:
    from rich.padding import Padding
    from rich.table import Table

    console.rule("[bold]Unused flavors", align="left")
    console.print()
    if unused_flavors:
        content = Table("Section", "Flavors")
        for path, flavors in unused_flavors.items():
            content.add_row(str(path), " ".join(sorted(flavors)))
    else:
        content = "None."
    console.print(Padding(content, (0, 0, 0, 2)))


def _print_unused_files_report(
    unused_files: "Iterable[Path]", git_dir: Path, console: "Console"
) -> None:
    from rich.padding import Padding
    from rich.table import Table

    console.rule("[bold]Unused content files", align="left")
    console.print()
    paths = sorted(unused_files)
    if paths:
        content = Table("File", "Frames")
        for path in paths:
            content.add_row(
                f"[link=file://{path}]{path.relative_to(git_dir)}[/link]",
                str(_frame_count(path)),
            )
    else:
        content = "None."
    console.print(Padding(content, (0, 0, 0, 2)))


def _frame_count(path: Path) -> int:
    """Count a Markdown file's frames: its level-1 headings, outside code blocks.

    Returns:
        The number of `# ` lines outside fenced code blocks.
    """
    count, fence = 0, ""
    for line in path.read_text(encoding="utf8").splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not fence:
                fence = marker
            elif marker == fence:
                fence = ""
        elif not fence and line.startswith("# "):
            count += 1
    return count


def _print_section_report(
    section: str,
    flavor: str | None,
    using: "Mapping[Path, Iterable[str]]",
    console: "Console",
) -> None:
    from rich.padding import Padding
    from rich.table import Table

    title = section
    if flavor is not None:
        title += f" {flavor}"
    console.rule(f"[bold]Decks depending on [italic]{title}", align="left")
    console.print()
    if using:
        content = Table("Deck", "Parts")
        for deck, part_names in using.items():
            content.add_row(str(deck), " ".join(sorted(part_names)))
    else:
        content = "None."
    console.print(Padding(content, (0, 0, 0, 2)))
