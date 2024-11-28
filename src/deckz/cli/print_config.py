from pathlib import Path

from . import app


@app.command()
def print_config(*, workdir: Path = Path()) -> None:
    """Print the resolved configuration.

    Args:
        workdir: Path to move into before running the command

    """
    from rich import print as rich_print

    from ..configuring.config import get_config
    from ..configuring.paths import Paths

    config = get_config(Paths.from_defaults(workdir))
    max_length = max(len(key) for key in config)
    rich_print(
        "\n".join((f"[green]{k:{max_length}}[/] {v}") for k, v in config.items())
    )
