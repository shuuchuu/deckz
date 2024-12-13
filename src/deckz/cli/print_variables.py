from pathlib import Path

from . import app


@app.command()
def print_variables(*, workdir: Path = Path()) -> None:
    """Print the resolved variables.

    Args:
        workdir: Path to move into before running the command

    """
    from rich import print as rich_print

    from ..configuring.settings import DeckSettings
    from ..configuring.variables import get_variables

    variables = get_variables(DeckSettings.from_yaml(workdir))
    max_length = max(len(key) for key in variables)
    rich_print(
        "\n".join((f"[green]{k:{max_length}}[/] {v}") for k, v in variables.items())
    )
