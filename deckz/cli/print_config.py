from pathlib import Path

from . import app, option_workdir


@app.command()
@option_workdir
def print_config(workdir: Path) -> None:
    """Print the resolved configuration."""
    from rich import print

    from ..config import get_config
    from ..paths import Paths

    config = get_config(Paths.from_defaults(workdir))
    max_length = max(len(key) for key in config)
    print("\n".join((f"[green]{k:{max_length}}[/] {v}") for k, v in config.items()))
