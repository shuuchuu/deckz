from pathlib import Path

from . import app


@app.command()
def settings(*, json: bool = False, workdir: Path = Path()) -> None:
    """Print the resolved settings.

    Those of the deck when `workdir` holds a `deck.yml`, the repository's
    otherwise.

    Args:
        json: Print them as one JSON object instead
        workdir: Path to move into before running the command
    """
    from rich import print as rich_print

    from ...configuring.settings import DeckSettings, GlobalSettings

    deck_settings = DeckSettings.from_yaml(workdir)
    resolved: GlobalSettings = (
        deck_settings
        if deck_settings.paths.deck_definition.is_file()
        else GlobalSettings.from_yaml(workdir)
    )
    if json:
        print(resolved.model_dump_json(indent=2))
        return
    rich_print(resolved)
