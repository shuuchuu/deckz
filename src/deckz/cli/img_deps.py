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
    from collections.abc import Mapping, Set

    from rich.console import Console
    from rich.table import Table

    from ..analyzing.images_analyzer import ImagesAnalyzer
    from ..configuring.settings import GlobalSettings
    from ..models.scalars import UnresolvedPath

    def _display_table(
        unlicensed_images: Mapping[UnresolvedPath, Set[Path]],
        console: Console,
    ) -> None:
        if unlicensed_images:
            table = Table("Section", "Unlicensed images")
            for section, images in unlicensed_images.items():
                table.add_row(str(section), f"{len(images)}")
            console.print(table)
        else:
            console.print("No unlicensed image!")

    def _display_section_images(
        unlicensed_images: Mapping[UnresolvedPath, Set[Path]],
        console: Console,
        shared_dir: Path,
    ) -> None:
        if unlicensed_images:
            for section, images in unlicensed_images.items():
                console.print()
                console.rule(
                    f"[bold]{section}[/] — "
                    f"[red]{len(images)}[/] "
                    f"unlicensed image{'s' * (len(images) > 1)}",
                    align="left",
                )
                console.print()
                for image in sorted(images):
                    matches = image.parent.glob(f"{image.name}.*")
                    console.print(
                        " or ".join(
                            f"[link=file://{m}]{m.relative_to(shared_dir)}[/link]"
                            for m in matches
                            if m.suffix != ".yml"
                        )
                    )
        else:
            console.print("No unlicensed image!")

    settings = GlobalSettings.from_yaml(workdir)
    console = Console(highlight=False)

    with console.status("Finding unlicensed images"):
        images_analyzer = ImagesAnalyzer(
            settings.paths.shared_dir, settings.paths.git_dir
        )
        unlicensed_images = images_analyzer.sections_unlicensed_images()
        sorted_unlicensed_images = {
            k: v
            for k, v in sorted(
                unlicensed_images.items(),
                key=lambda t: len(t[1]),
                reverse=descending,
            )
            if v
        }
    if verbose:
        console.print("[bold]Sections and their unlicensed images[/]")
        _display_section_images(
            sorted_unlicensed_images, console, settings.paths.shared_dir
        )
    else:
        _display_table(sorted_unlicensed_images, console)
