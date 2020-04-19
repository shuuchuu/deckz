from argparse import ArgumentParser
from logging import getLogger
from shutil import copy as shutil_copy

from deckz.cli import register_command
from deckz.paths import Paths


def _parser_definer(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--deck-path",
        dest="paths",
        type=Paths,
        default=".",
        help="Path of the deck, defaults to `%(default)s`.",
    )


@register_command(parser_definer=_parser_definer)
def init(paths: Paths) -> None:
    """Create an initial targets.yml."""
    logger = getLogger(__name__)
    if paths.targets.exists():
        logger.info(f"Nothing to do: {paths.targets} already exists")

    else:
        logger.info(f"Copying {paths.template_targets} to current directory")
        shutil_copy(str(paths.template_targets), str(paths.working_dir))
