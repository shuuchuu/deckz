from pathlib import Path

from . import WorkdirOption, app


@app.command()
def print_config(workdir: WorkdirOption = Path(".")) -> None:
    """Print the resolved configuration."""
    from rich import print

    from ..configuring.config import get_config
    from ..configuring.paths import Paths

    config = get_config(Paths.from_defaults(workdir))
    max_length = max(len(key) for key in config)
    print("\n".join((f"[green]{k:{max_length}}[/] {v}") for k, v in config.items()))
