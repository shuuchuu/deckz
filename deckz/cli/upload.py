from pathlib import Path

from ..cli import app, option_workdir


@app.command()
@option_workdir
def upload(workdir: Path) -> None:
    """Upload pdfs to Google Drive."""
    from ..paths import Paths
    from ..uploading import Uploader

    paths = Paths.from_defaults(workdir)
    Uploader(paths)
