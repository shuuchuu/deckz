from pathlib import Path
from typing import TYPE_CHECKING

from . import app

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Set

    from rich.console import Console


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

    from ..configuring.paths import GlobalPaths
    from ..processing.section_stats import SectionStatsProcessor
    from ..repository import decks_iterator

    if not unused and section is None:
        return

    paths = GlobalPaths.from_defaults(workdir)

    console = Console()

    with console.status("Processing decks"):
        deck_paths, decks = zip(*decks_iterator(paths.git_dir), strict=True)
        section_stats_processor = SectionStatsProcessor()
        section_stats_list = [section_stats_processor.process(deck) for deck in decks]

    if unused:
        unused_flavors = _compute_unused_flavors(
            paths.shared_latex_dir, section_stats_list
        )
        _print_unused_report(unused_flavors, console)

    if section is not None:
        if unused:
            console.print()
        using = _compute_decks_using_flavor(
            section, flavor, section_stats_list, deck_paths
        )
        _print_section_report(section, flavor, using, console)


def _compute_unused_flavors(
    shared_latex_dir: Path,
    section_stats_list: "Iterable[Mapping[str, Set[tuple[Path, str]]]]",
) -> dict[Path, set[str]]:
    from itertools import chain

    from ..repository import shared_sections_iterator

    unused_flavors = {
        p: set(d.flavors) for p, d in shared_sections_iterator(shared_latex_dir)
    }
    for section_stats in section_stats_list:
        for path, section_flavor in chain(*section_stats.values()):
            path = path.relative_to("/")
            if path in unused_flavors and section_flavor in unused_flavors[path]:
                unused_flavors[path].remove(section_flavor)
                if not unused_flavors[path]:
                    del unused_flavors[path]
    return unused_flavors


def _compute_decks_using_flavor(
    section: str,
    flavor: str,
    section_stats_list: "Iterable[Mapping[str, Set[tuple[Path, str]]]]",
    deck_paths: "Iterable[Path]",
):
    section_path = Path(section)
    using = {}
    for deck_path, section_stats in zip(deck_paths, section_stats_list, strict=True):
        for part_name, flavors in section_stats.items():
            for path, part_flavor in flavors:
                if path.relative_to("/") == section_path and (
                    flavor is None or flavor == part_flavor
                ):
                    if deck_path not in using:
                        using[deck_path] = set()
                    using[deck_path].add(part_name)
    return using


def _print_unused_report(
    unused_flavors: "Mapping[Path, Iterable[str]]", console: "Console"
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
