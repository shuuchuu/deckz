from typing import List, Optional

from typer import Argument

from deckz.cli import app
from deckz.paths import Paths
from deckz.runner import run as runner_run


@app.command()
def run(
    targets: Optional[List[str]] = Argument(None),
    handout: bool = True,
    presentation: bool = True,
    print: bool = True,
    deck_path: str = ".",
) -> None:
    """Compile main targets."""
    paths = Paths(deck_path)
    runner_run(
        paths=paths,
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
        target_whitelist=targets,
    )
