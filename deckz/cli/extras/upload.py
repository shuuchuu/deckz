from pathlib import Path

from .. import app


@app.command()
def upload(*, workdir: Path = Path()) -> None:
    """Upload pdfs to Google Drive.

    Args:
        workdir: Path to move into before running the command

    """
    from ...configuring.paths import Paths
    from ...extras.uploading import Uploader

    paths = Paths.from_defaults(workdir)
    Uploader(paths)
