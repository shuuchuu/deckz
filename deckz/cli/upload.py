from logging import getLogger
from pathlib import Path

from deckz.cli import app, option_workdir
from deckz.paths import Paths
from deckz.uploading import Uploader

_logger = getLogger(__name__)


@app.command()
@option_workdir
def upload(workdir: Path) -> None:
    """Upload pdfs to Google Drive."""
    paths = Paths.from_defaults(workdir)
    Uploader(paths)
