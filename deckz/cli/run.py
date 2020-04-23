from typing import List

from deckz.cli import command, deck_path_option, option, target_whitelist_argument
from deckz.paths import Paths
from deckz.runner import run as runner_run


@command
@target_whitelist_argument
@deck_path_option
@option(
    "--handout/--no-handout", default=True, help="Compile the handout.",
)
@option(
    "--presentation/--no-presentation", default=True, help="Compile the presentation.",
)
@option(
    "--verbose-latexmk/--no-verbose-latexmk",
    default=False,
    help="Make latexmk verbose.",
)
def run(
    deck_path: str,
    target_whitelist: List[str],
    handout: bool,
    presentation: bool,
    verbose_latexmk: bool,
) -> None:
    """Compile main targets."""
    paths = Paths(deck_path)
    runner_run(
        paths=paths,
        handout=handout,
        presentation=presentation,
        verbose_latexmk=verbose_latexmk,
        debug=False,
        target_whitelist=target_whitelist,
    )
