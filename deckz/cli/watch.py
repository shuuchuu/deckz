from logging import getLogger
from pathlib import Path
from typing import List, Optional

from typer import Argument

from deckz.cli import app
from deckz.paths import Paths
from deckz.watching import watch as watching_watch


_logger = getLogger(__name__)


@app.command()
def watch(
    targets: Optional[List[str]] = Argument(None),
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,
    minimum_delay: int = 5,
    deck_path: Path = Path("."),
) -> None:
    """Compile on change."""
    _logger.info("Watching current and shared directories")
    watching_watch(
        minimum_delay=minimum_delay,
        paths=Paths.from_defaults(deck_path),
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
        target_whitelist=targets,
    )
