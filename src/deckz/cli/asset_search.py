from pathlib import Path

from . import app


@app.command()
def asset_search(asset: str, /, *, workdir: Path = Path()) -> None:
    """Find which files use ASSET.

    Args:
        asset: Asset to search in files. Specify the path relative to the shared \
            directory and whithout extension, e.g. img/turing
        workdir: Path to move into before running the command

    """
    from rich.console import Console

    from ..components.factory import GlobalSettingsFactory
    from ..configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)

    console = Console(highlight=False)

    assets_searcher = GlobalSettingsFactory(settings).assets_searcher()
    with console.status("Processing decks"):
        result = assets_searcher.search(asset)

    for path in result:
        console.print(
            f"[link=file://{path}]{path.relative_to(settings.paths.git_dir)}[/link]"
        )
