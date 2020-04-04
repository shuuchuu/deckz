from functools import partial
from logging import getLogger, INFO
from pathlib import Path
from pprint import pformat
from sys import exit

from click import command, option
from coloredlogs import install as coloredlogs_install

from deckz.builder import build
from deckz.config import get_config
from deckz.targets import get_targets
from deckz.utils import get_workdir_path


option = partial(option, show_default=True)  # type: ignore


@command()
@option("--handout/--no-handout", default=True, help="Compile the handout.")
@option(
    "--presentation/--no-presentation", default=True, help="Compile the presentation.",
)
@option(
    "--debug/--no-debug",
    default=False,
    help="Activate debug mode: targets-debug.yml will be used instead of targets.yml",
)
@option(
    "--silent-latexmk/--no-silent-latexmk", default=True, help="Make latexmk silent."
)
@option(
    "--print-config/--no-print-config",
    default=False,
    help="Print the resolved configuration.",
)
def main(
    handout: bool,
    presentation: bool,
    debug: bool,
    silent_latexmk: bool,
    print_config: bool,
) -> None:
    """Entry point of the deckz tool."""
    coloredlogs_install(
        level=INFO, fmt="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S",
    )
    logger = getLogger(__name__)
    workdir = get_workdir_path()
    if workdir is None:
        logger.critical(
            "Could not find the path of the current git working directory. "
            "Are you in one?"
        )
        exit(1)
    if not Path(".").resolve().relative_to(workdir.resolve()).match("*/*"):
        logger.critical(
            f"Not deep enough from root {workdir}. "
            "Please follow the directory hierarchy root > company > deck and invoke "
            "this tool from the deck directory."
        )
        exit(1)
    config = get_config()
    if print_config:
        logger.info(f"Resolved config as:\n{pformat(config)}")
    targets = get_targets(debug=debug)
    for i, target in enumerate(targets, start=1):
        if handout:
            logger.info(f"Building handout for target {i}/{len(targets)}")
            build(
                config=config,
                target=target,
                handout=True,
                silent_latexmk=silent_latexmk,
            )
        if presentation:
            logger.info(f"Building presentation for target {i}/{len(targets)}")
            build(
                config=config,
                target=target,
                handout=False,
                silent_latexmk=silent_latexmk,
            )
