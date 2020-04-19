from argparse import ArgumentParser
from logging import getLogger

from deckz.cli import register_command
from deckz.config import get_config
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
def print_config(paths: Paths) -> None:
    """Print the resolved configuration."""
    logger = getLogger(__name__)
    config = get_config(paths)
    logger.info(
        "Resolved config as:\n%s",
        "\n".join((f"  - {k}: {v}") for k, v in config.items()),
    )
