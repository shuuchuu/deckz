from logging import getLogger
from pathlib import Path

from deckz.cli import app
from deckz.paths import Paths
from deckz.uploading import Uploader


_logger = getLogger(__name__)


@app.command()
def upload(deck_path: Path = Path(".")) -> None:
    """Upload pdfs to Google Drive."""
    paths = Paths.from_defaults(deck_path)
    Uploader(paths)
