from pathlib import Path

from deckz.cli import app
from deckz.running import run_all as running_run_all


@app.command()
def check_all(
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,
    directory: Path = Path("."),
) -> None:
    """Compile all shared slides."""
    running_run_all(
        directory=directory,
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
    )
