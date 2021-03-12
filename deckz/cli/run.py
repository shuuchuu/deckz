from pathlib import Path
from typing import List, Optional

from typer import Argument

from deckz.cli import app
from deckz.paths import Paths
from deckz.running import run as running_run


@app.command()
def run(
    targets: Optional[List[str]] = Argument(None),
    handout: bool = True,
    presentation: bool = True,
    print: bool = True,
    deck_path: Path = Path("."),
) -> None:
    """Compile main targets."""
    paths = Paths.from_defaults(deck_path)
    running_run(
        paths=paths,
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
        target_whitelist=targets,
    )
