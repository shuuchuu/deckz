from pathlib import Path

from . import app


@app.command()
def clean(*, workdir: Path = Path()) -> None:
    """Wipe the build directory.

    Args:
        workdir: Path to move into before running the command

    """
    from logging import getLogger
    from shutil import rmtree

    from ..configuring.settings import DeckSettings

    logger = getLogger(__name__)
    settings = DeckSettings.from_yaml(workdir)
    if not settings.paths.build_dir.exists():
        logger.info(f"Nothing to do: {settings.paths.build_dir} doesn't exist")
    else:
        logger.info(f"Deleting {settings.paths.build_dir}")
        rmtree(settings.paths.build_dir)
