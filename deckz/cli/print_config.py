from pathlib import Path

from rich import print
from typer import Option

from deckz.cli import app
from deckz.config import get_config
from deckz.paths import Paths


@app.command()
def print_config(
    workdir: Path = Option(
        Path("."), help="Path to move into before running the command"
    )
) -> None:
    """Print the resolved configuration."""
    config = get_config(Paths.from_defaults(workdir))
    max_length = max(len(key) for key in config)
    print("\n".join((f"[green]{k:{max_length}}[/] {v}") for k, v in config.items()))
