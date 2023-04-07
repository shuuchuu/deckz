from pathlib import Path

from rich import print

from deckz.cli import app, option_workdir
from deckz.config import get_config
from deckz.paths import Paths


@app.command()
@option_workdir
def print_config(workdir: Path) -> None:
    """Print the resolved configuration."""
    config = get_config(Paths.from_defaults(workdir))
    max_length = max(len(key) for key in config)
    print("\n".join((f"[green]{k:{max_length}}[/] {v}") for k, v in config.items()))
