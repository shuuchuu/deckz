from pathlib import Path
from typing import TYPE_CHECKING

from . import app

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from rich.console import Console

    from ..models import UnresolvedPath


@app.command()
def deps(
    section: str | None = None,
    flavor: str | None = None,
    /,
    *,
    unused: bool = True,
    workdir: Path = Path(),
) -> None:
    """Display information about shared sections and flavors usage.

    Args:
        section: Restrict the output to only this section
        flavor: Restrict the output further to only this section
        unused: Display unused flavors
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
        settings.paths.shared_latex_dir, settings.paths.git_dir
    )

    if unused:
        with console.status("Processing decks"):
            _print_unused_report(sections_analyzer.unused_flavors(), console)

    if section is not None:
        if unused:
            console.print()
        with console.status("Processing decks"):
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
    console.print(Padding(content if unused_flavors else "None.", (0, 0, 0, 2)))


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
    console.print(Padding(content if using else "None.", (0, 0, 0, 2)))
