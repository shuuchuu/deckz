from pathlib import Path

from . import app


@app.command()
def all(*, workdir: Path = Path()) -> None:  # ruff: ignore[builtin-variable-shadowing]
    """Wipe all build directories, and every check/run-preview scratch dir.

    Args:
        workdir: Path to move into before running the command

    """
    from logging import getLogger
    from shutil import rmtree

    from ...utils import all_deck_settings, get_git_dir

    logger = getLogger(__name__)
    git_dir = get_git_dir(workdir).resolve()
    for settings in all_deck_settings(git_dir):
        if not settings.paths.build_dir.exists():
            logger.info(f"Nothing to do: {settings.paths.build_dir} doesn't exist")
        else:
            logger.info(f"Deleting {settings.paths.build_dir}")
            rmtree(settings.paths.build_dir)
    for scratch_dir in (git_dir / ".check", git_dir / ".run"):
        if scratch_dir.is_dir():
            logger.info(f"Deleting {scratch_dir}")
            rmtree(scratch_dir)
