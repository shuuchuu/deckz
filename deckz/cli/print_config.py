from logging import getLogger

from deckz.cli import command, deck_path_option
from deckz.config import get_config
from deckz.paths import Paths


@command
@deck_path_option
def print_config(deck_path: str) -> None:
    """Print the resolved configuration."""
    logger = getLogger(__name__)
    paths = Paths(deck_path)
    config = get_config(paths)
    logger.info(
        "Resolved config as:\n%s",
        "\n".join((f"  - {k}: {v}") for k, v in config.items()),
    )
