from pathlib import Path

from . import app


@app.command()
def print_settings(*, workdir: Path = Path()) -> None:
    """Print the resolved settings.

    Args:
        workdir: Path to move into before running the command
    """
    from pydantic import ValidationError
    from rich import print as rich_print

    from ..configuring.settings import DeckSettings, GlobalSettings

    try:
        settings: GlobalSettings = DeckSettings.from_yaml(workdir)
    except ValidationError:
        settings = GlobalSettings.from_yaml(workdir)
    rich_print(settings)
