from logging import getLogger
from pathlib import Path
from shutil import rmtree

from deckz.cli import app
from deckz.paths import Paths


@app.command()
def clean(deck_path: Path = Path(".")) -> None:
    """Wipe the build directory."""
    logger = getLogger(__name__)
    paths = Paths.from_defaults(deck_path)
    if not paths.build_dir.exists():
        logger.info(f"Nothing to do: {paths.build_dir} doesn't exist")
    else:
        logger.info(f"Deleting {paths.build_dir}")
        rmtree(paths.build_dir)
