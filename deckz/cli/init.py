from logging import getLogger
from shutil import copy as shutil_copy

from deckz.cli import command, deck_path_option
from deckz.paths import Paths


@command
@deck_path_option
def init(deck_path: str) -> None:
    """Create an initial targets.yml."""
    logger = getLogger(__name__)
    paths = Paths(deck_path)
    if paths.targets.exists():
        logger.info(f"Nothing to do: {paths.targets} already exists")

    else:
        logger.info(f"Copying {paths.template_targets} to current directory")
        shutil_copy(str(paths.template_targets), str(paths.current_dir))
