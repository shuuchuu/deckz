from logging import getLogger

from deckz.cli import command, deck_path_option, option
from deckz.paths import Paths
from deckz.targets import Targets


@command
@deck_path_option
@option(
    "--dry-run/--do-it",
    default=True,
    help="Print what would be removed instead of removing it.",
)
def clean_latex(deck_path: str, dry_run: bool) -> None:
    """Clean LaTeX files that are not used in `targets*.yml`."""
    logger = getLogger(__name__)
    logger.info("Cleaning unused LaTeX files")
    paths = Paths(deck_path)
    dependencies_dict = Targets(
        paths=paths, fail_on_missing=False, whitelist=[]
    ).get_dependencies()
    for target_name, dependencies in dependencies_dict.items():
        logger.info(f"Processing target {target_name}")
        if dependencies.unused:
            logger.info(
                "%s the following unused dependencies:\n%s",
                "Would remove" if dry_run else "Removing",
                "\n".join(f"  - {str(d)}" for d in sorted(dependencies.unused)),
            )
        else:
            logger.info("All LaTeX files are used, nothing to remove")
        if not dry_run:
            for dependency in dependencies.unused:
                dependency.unlink()
