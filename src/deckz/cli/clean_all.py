from pathlib import Path

from . import app


@app.command()
def clean_all(*, workdir: Path = Path()) -> None:
    """Wipe all build directories.

    Args:
        workdir: Path to move into before running the command

    """
    from logging import getLogger
    from shutil import rmtree

    from ..utils import all_deck_settings, get_git_dir

    logger = getLogger(__name__)
    for settings in all_deck_settings(get_git_dir(workdir).resolve()):
        if not settings.paths.build_dir.exists():
            logger.info(f"Nothing to do: {settings.paths.build_dir} doesn't exist")
        else:
            logger.info(f"Deleting {settings.paths.build_dir}")
            rmtree(settings.paths.build_dir)
