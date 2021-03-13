from logging import getLogger
from pathlib import Path

from deckz.cli import app
from deckz.paths import GlobalPaths
from deckz.watching import watch_standalones as watching_watch_standalones


_logger = getLogger(__name__)


@app.command()
def watch_standalones(minimum_delay: int = 5, current_dir: Path = Path(".")) -> None:
    """Compile standalones on change."""
    watching_watch_standalones(
        minimum_delay, current_dir, GlobalPaths.from_defaults(current_dir)
    )
