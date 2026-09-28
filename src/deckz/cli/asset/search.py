from pathlib import Path

from . import app


@app.command()
def search(asset: str, /, *, json: bool = False, workdir: Path = Path()) -> None:
    """Find which files use ASSET.

    Args:
        asset: Asset to search in files. Specify the path relative to the assets \
            directory and whithout extension, e.g. img/turing
        json: Print one JSON array of the files' paths, relative to the \
            repository root, instead
        workdir: Path to move into before running the command

    """
    from rich.console import Console

    from ...components.factory import GlobalSettingsFactory
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)

    console = Console(highlight=False)

    assets_searcher = GlobalSettingsFactory(settings).assets_searcher()
    with console.status("Processing decks"):
        result = assets_searcher.search(asset)

    if json:
        from .._presentation import print_json

        git_dir = settings.paths.git_dir
        print_json(sorted(str(path.relative_to(git_dir)) for path in result))
        return
    for path in result:
        console.print(
            f"[link=file://{path}]{path.relative_to(settings.paths.git_dir)}[/link]"
        )
