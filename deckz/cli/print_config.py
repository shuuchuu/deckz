from pathlib import Path

from typing_extensions import Annotated

from . import WorkdirOption, app


@app.command()
def print_config(workdir: Annotated[Path, WorkdirOption] = Path(".")) -> None:
    """Print the resolved configuration."""
    from rich import print

    from ..config import get_config
    from ..paths import Paths

    config = get_config(Paths.from_defaults(workdir))
    max_length = max(len(key) for key in config)
    print("\n".join((f"[green]{k:{max_length}}[/] {v}") for k, v in config.items()))
