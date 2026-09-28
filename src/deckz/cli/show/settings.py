from pathlib import Path

from . import app


@app.command()
def settings(*, json: bool = False, workdir: Path = Path()) -> None:
    """Print the resolved settings.

    Args:
        json: Print them as one JSON object instead
        workdir: Path to move into before running the command
    """
    from pydantic import ValidationError
    from rich import print as rich_print

    from ...configuring.settings import DeckSettings, GlobalSettings

    try:
        resolved: GlobalSettings = DeckSettings.from_yaml(workdir)
    except ValidationError:
        resolved = GlobalSettings.from_yaml(workdir)
    if json:
        print(resolved.model_dump_json(indent=2))
        return
    rich_print(resolved)
