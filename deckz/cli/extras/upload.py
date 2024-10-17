from pathlib import Path

from .. import WorkdirOption, app


@app.command()
def upload(workdir: WorkdirOption = Path(".")) -> None:
    """Upload pdfs to Google Drive."""
    from ...configuring.paths import Paths
    from ...extras.uploading import Uploader

    paths = Paths.from_defaults(workdir)
    Uploader(paths)
