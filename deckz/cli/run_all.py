from pathlib import Path

from deckz.cli import app
from deckz.runner import run_all as runner_run_all


@app.command()
def run_all(
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,
    directory: Path = Path("."),
) -> None:
    """Compile all shared slides."""
    runner_run_all(
        directory=directory,
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
    )
