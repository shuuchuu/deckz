from logging import getLogger
from pathlib import Path
from shutil import rmtree

from deckz.cli import app, option_workdir
from deckz.paths import Paths


@app.command()
@option_workdir
def clean(workdir: Path) -> None:
    """Wipe the build directory."""
    logger = getLogger(__name__)
    paths = Paths.from_defaults(workdir)
    if not paths.build_dir.exists():
        logger.info(f"Nothing to do: {paths.build_dir} doesn't exist")
    else:
        logger.info(f"Deleting {paths.build_dir}")
        rmtree(paths.build_dir)
