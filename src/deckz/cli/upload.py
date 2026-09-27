from pathlib import Path

from . import app


@app.command()
def upload(*, workdir: Path = Path()) -> None:
    """Upload pdfs to Google Drive.

    Args:
        workdir: Path to move into before running the command

    """
    from ..configuring.settings import DeckSettings
    from ..extras import extras_imports

    with extras_imports():
        from ..extras.uploading import Uploader

    Uploader(DeckSettings.from_yaml(workdir))
