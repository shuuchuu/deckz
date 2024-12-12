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

    from ..configuring.paths import GlobalPaths
    from ..utils import all_paths

    logger = getLogger(__name__)
    global_paths = GlobalPaths(current_dir=workdir)
    for paths in all_paths(global_paths.git_dir):
        if not paths.build_dir.exists():
            logger.info(f"Nothing to do: {paths.build_dir} doesn't exist")
        else:
            logger.info(f"Deleting {paths.build_dir}")
            rmtree(paths.build_dir)
