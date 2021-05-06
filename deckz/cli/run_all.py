from pathlib import Path

from deckz.cli import app
from deckz.running import run_all as running_run_all


@app.command()
def run_all(
    handout: bool = True,
    presentation: bool = True,
    print: bool = True,
    directory: Path = Path("."),
) -> None:
    """Compile all shared slides (all formats by default)."""
    running_run_all(
        directory=directory,
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
    )
