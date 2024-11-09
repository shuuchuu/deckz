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

    from ..configuring.paths import Paths

    logger = getLogger(__name__)
    paths = Paths.from_defaults(workdir)
    if not paths.build_dir.exists():
        logger.info(f"Nothing to do: {paths.build_dir} doesn't exist")
    else:
        logger.info(f"Deleting {paths.build_dir}")
        rmtree(paths.build_dir)
