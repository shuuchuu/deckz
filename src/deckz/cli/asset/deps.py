from pathlib import Path

from . import app


@app.command()
def deps(
    *,
    verbose: bool = True,
    descending: bool = True,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Find unlicensed assets with output detailed by section.

    Args:
        verbose: Detailed output with a listing of used assets
        descending: Sort sections by ascending number of unlicensed assets
        json: Print one JSON array instead, of objects with a "section" and
            its unlicensed "assets" (relative to the assets directory,
            without extension), sorted as the table would be
        workdir: Path to move into before running the command

    """
    from collections.abc import Mapping, Set

    from rich.console import Console
    from rich.table import Table

    from ...components.factory import GlobalSettingsFactory
    from ...configuring.settings import GlobalSettings
    from ...models import UnresolvedPath

    def _display_table(
        unlicensed_assets: Mapping[UnresolvedPath, Set[Path]],
        console: Console,
    ) -> None:
        if unlicensed_assets:
            table = Table("Section", "Unlicensed assets")
            for section, images in unlicensed_assets.items():
                table.add_row(str(section), f"{len(images)}")
            console.print(table)
        else:
            console.print("No unlicensed asset!")

    def _display_section_assets(
        unlicensed_assets: Mapping[UnresolvedPath, Set[Path]],
        console: Console,
        assets_dir: Path,
    ) -> None:
        if unlicensed_assets:
            for section, images in unlicensed_assets.items():
                console.print()
                console.rule(
                    f"[bold]{section}[/] — "
                    f"[red]{len(images)}[/] "
                    f"unlicensed asset{'s' * (len(images) > 1)}",
                    align="left",
                )
                console.print()
                for image in sorted(images):
                    matches = image.parent.glob(f"{image.name}.*")
                    console.print(
                        " or ".join(
                            f"[link=file://{m}]{m.relative_to(assets_dir)}[/link]"
                            for m in matches
                            if m.suffix != ".yml"
                        )
                    )
        else:
            console.print("No unlicensed asset!")

    settings = GlobalSettings.from_yaml(workdir)
    console = Console(highlight=False)

    with Console(stderr=True).status("Finding unlicensed assets"):
        assets_analyzer = GlobalSettingsFactory(settings).assets_analyzer()
        unlicensed_assets = assets_analyzer.sections_unlicensed_images()
        sorted_unlicensed_assets = {
            k: v
            for k, v in sorted(
                unlicensed_assets.items(),
                key=lambda t: len(t[1]),
                reverse=descending,
            )
            if v
        }
    if json:
        from .._presentation import print_json

        assets_dir = settings.paths.assets_dir
        print_json(
            [
                {
                    "section": str(section),
                    "assets": sorted(
                        str(image.relative_to(assets_dir)) for image in images
                    ),
                }
                for section, images in sorted_unlicensed_assets.items()
            ]
        )
    elif verbose:
        console.print("[bold]Sections and their unlicensed assets[/]")
        _display_section_assets(
            sorted_unlicensed_assets, console, settings.paths.assets_dir
        )
    else:
        _display_table(sorted_unlicensed_assets, console)
