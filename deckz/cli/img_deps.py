from pathlib import Path

from . import app


@app.command()
def img_deps(
    sections: list[str] | None = None,
    /,
    *,
    verbose: bool = True,
    descending: bool = True,
    workdir: Path = Path(),
) -> None:
    """Find unlicensed images with output detailed by section.

    You can display info only about specific SECTIONS, like nn/cnn or tools."

    Args:
        sections: Restrict the output to these sections
        verbose: Detailed output with a listing of used images
        descending: Sort sections by ascending number of unlicensed images
        workdir: Path to move into before running the command

    """
    from collections.abc import Iterable, Iterator, Mapping, Set, Sized
    from re import compile as re_compile

    from rich.console import Console
    from rich.table import Table
    from yaml import safe_load

    from ..configuring.paths import GlobalPaths
    from ..exceptions import DeckzError
    from ..parsing.targets import Dependencies, Targets

    def _display_table(
        sections: Iterable[str],
        images: Mapping[str, Set[str]],
        console: Console,
    ) -> None:
        table = Table("Section", "Unlicensed images")
        for section in sections:
            try:
                section_images = images[section]
            except KeyError:
                console.print(
                    f"[red]Could not find section [white]{section}[/], aborting[/]"
                )
                return
            if section_images:
                table.add_row(section, f"{len(section_images)}")
        if table.row_count:
            console.print(table)
        else:
            console.print("No unlicensed image!")

    def _display_section_images(
        section: str,
        images: Mapping[str, Set[str]],
        console: Console,
        global_paths: GlobalPaths,
    ) -> None:
        section_images = images[section]
        if not section_images:
            return
        console.print()
        console.rule(
            f"[bold]{section}[/] — "
            f"[red]{len(section_images)}[/] "
            f"unlicensed image{'s' * (len(section_images) > 1)}",
            align="left",
        )
        console.print()
        for image in sorted(section_images):
            image_path = global_paths.shared_dir / image
            matches = image_path.parent.glob(f"{image_path.name}.*")
            console.print(
                " or ".join(
                    f"[link=file://{m}]{m.relative_to(global_paths.current_dir)}[/link]"
                    for m in matches
                    if m.suffix != ".yml"
                )
            )

    def _ordered_sections(
        dependencies: Mapping[str, Dependencies],
        images: Mapping[str, Sized],
        sections: Iterable[str],
        console: Console,
        descending: bool,
    ) -> list[str]:
        sections = sections or []
        unknown_sections = sorted(
            section for section in sections if section not in dependencies
        )
        if unknown_sections:
            to_print = ", ".join(f"[white]{section}[/]" for section in unknown_sections)
            console.print(
                f"[red]Could not find section{'s' * (len(unknown_sections) > 1)} "
                f"{to_print}."
            )
            msg = f"could not find sections {', '.join(sections)}."
            raise DeckzError(msg)
        return sorted(
            sections or dependencies, key=lambda s: len(images[s]), reverse=descending
        )

    _pattern = re_compile(r'\\V{\[?"(.+?)".*\]? \| image}')

    def _section_images(
        section: str, dependencies: Dependencies, global_paths: GlobalPaths
    ) -> Iterator[str]:
        for latex_file in dependencies.used:
            for match in _pattern.finditer(latex_file.read_text(encoding="utf8")):
                if match is None:
                    continue
                image = match.group(1)
                if not _image_license(image, global_paths):
                    yield image

    def _image_license(image: str, global_paths: GlobalPaths) -> str | None:
        metadata_path = (global_paths.shared_dir / image).with_suffix(".yml")
        if not metadata_path.exists():
            return None
        metadata = safe_load(metadata_path.read_text(encoding="utf8"))
        return metadata["license"]

    global_paths = GlobalPaths.from_defaults(workdir)
    console = Console(highlight=False)
    with console.status("Computing full section dependencies"):
        section_dependencies: dict[str, Dependencies] = {}
        for paths in global_paths.decks_paths():
            targets = Targets.from_file(paths)
            for target in targets:
                section_dependencies = Dependencies.merge_dicts(
                    section_dependencies, target.section_dependencies
                )
    with console.status("Computing images used by section"):
        images = {}
        for section, dependencies in section_dependencies.items():
            images[section] = set(_section_images(section, dependencies, global_paths))
    to_iterate = _ordered_sections(
        section_dependencies, images, sections or [], console, descending
    )
    if verbose:
        console.print("[bold]Sections and their unlicensed images[/]")
        for section in to_iterate:
            _display_section_images(section, images, console, global_paths)
    else:
        _display_table(to_iterate, images, console)
