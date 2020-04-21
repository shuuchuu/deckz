from argparse import ArgumentParser
from logging import getLogger

from deckz.cli import register_command
from deckz.paths import Paths
from deckz.targets import Dependencies, Targets


def _parser_definer(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would be removed.",
    )
    parser.add_argument(
        "--deck-path",
        dest="paths",
        type=Paths,
        default=".",
        help="Path of the deck, defaults to `%(default)s`.",
    )


@register_command(parser_definer=_parser_definer)
def clean_latex(paths: Paths, dry_run: bool) -> None:
    """Clean LaTeX files that are not used in `targets*.yml`."""
    logger = getLogger(__name__)
    logger.info(f"Cleaning unused LaTeX files")
    dependencies_dict = Dependencies.merge_dicts(
        Targets(
            paths=paths, debug=False, fail_on_missing=False, whitelist=[]
        ).get_dependencies(),
        Targets(
            paths=paths, debug=True, fail_on_missing=False, whitelist=[]
        ).get_dependencies(),
    )
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
