from logging import getLogger

from deckz.cli import (
    command,
    deck_path_option,
)
from deckz.paths import Paths
from deckz.uploader import Uploader


_logger = getLogger(__name__)


@command
@deck_path_option
def upload(deck_path: str) -> None:
    """Upload pdfs to Google Drive."""
    paths = Paths(deck_path)
    Uploader(paths)
