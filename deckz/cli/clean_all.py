from pathlib import Path

from . import app, option_workdir


@app.command()
@option_workdir
def clean_all(workdir: Path) -> None:
    """Wipe all build directories."""
    from logging import getLogger
    from shutil import rmtree

    from ..paths import GlobalPaths, Paths

    logger = getLogger(__name__)
    paths = GlobalPaths.from_defaults(workdir)
    for deck_path in (p.parent for p in paths.git_dir.glob("**/targets.yml")):
        deck_paths = Paths.from_defaults(deck_path)
        if not deck_paths.build_dir.exists():
            logger.info(f"Nothing to do: {deck_paths.build_dir} doesn't exist")
        else:
            logger.info(f"Deleting {deck_paths.build_dir}")
            rmtree(deck_paths.build_dir)
