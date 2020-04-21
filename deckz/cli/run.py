from argparse import ArgumentParser
from typing import List

from deckz.cli import register_command
from deckz.paths import Paths
from deckz.runner import run as runner_run


def _parser_definer(parser: ArgumentParser) -> None:
    parser.add_argument(
        "target_whitelist",
        metavar="targets",
        nargs="*",
        help="Targets to restrict to. No argument = consider everything.",
    )
    parser.add_argument(
        "--no-handout",
        dest="handout",
        action="store_false",
        help="Don't compile the handout.",
    )
    parser.add_argument(
        "--no-presentation",
        dest="presentation",
        action="store_false",
        help="Don't compile the presentation.",
    )
    parser.add_argument(
        "--verbose-latexmk", action="store_true", help="Make latexmk verbose."
    )
    parser.add_argument(
        "--deck-path",
        dest="paths",
        type=Paths,
        default=".",
        help="Path of the deck, defaults to `%(default)s`.",
    )


@register_command(parser_definer=_parser_definer)
def run(
    paths: Paths,
    target_whitelist: List[str],
    handout: bool,
    presentation: bool,
    verbose_latexmk: bool,
) -> None:
    """Compile main targets."""
    runner_run(
        paths=paths,
        handout=handout,
        presentation=presentation,
        verbose_latexmk=verbose_latexmk,
        debug=False,
        target_whitelist=target_whitelist,
    )
