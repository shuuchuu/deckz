from functools import partial
from logging import getLogger, INFO
from pathlib import Path
from pprint import pformat
from typing import Any, Dict, Set

from click import group, option
from coloredlogs import install as coloredlogs_install

from deckz.builder import build
from deckz.config import get_config
from deckz.paths import Paths
from deckz.targets import get_targets


option = partial(option, show_default=True)  # type: ignore


_logger = getLogger(__name__)


@group(chain=True)
def cli() -> None:
    coloredlogs_install(
        level=INFO, fmt="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S",
    )


@cli.command()
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
def run(handout: bool, presentation: bool, debug: bool, silent_latexmk: bool) -> None:
    """Compile targets."""
    paths = Paths(".")
    config = get_config(paths=paths)
    targets = get_targets(debug=debug, paths=paths, fail_on_missing=True)
    for i, target in enumerate(targets, start=1):
        if handout:
            _logger.info(f"Building handout for target {i}/{len(targets)}")
            build(
                config=config,
                target=target,
                handout=True,
                silent_latexmk=silent_latexmk,
                paths=paths,
            )
        if presentation:
            _logger.info(f"Building presentation for target {i}/{len(targets)}")
            build(
                config=config,
                target=target,
                handout=False,
                silent_latexmk=silent_latexmk,
                paths=paths,
            )


@cli.command()
def print_config() -> None:
    """Print the resolved configuration."""
    paths = Paths(".")
    config = get_config(paths=paths)
    _logger.info(f"Resolved config as:\n{pformat(config)}")


@cli.command()
def clean_latex() -> None:
    """Clean LaTeX files that are not used in `targets*.yml`."""

    def find_includes(input_dict: Dict[str, Any]) -> Set[str]:
        includes: Set[str] = set()

        for key, value in input_dict.items():
            if key == "includes":
                includes.update(value)

            elif isinstance(value, dict):
                includes.update(find_includes(value))

            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        includes.update(find_includes(item))
        return includes

    _logger.info(f"Cleaning unused LaTeX files")
    paths = Paths(".")
    includes = set(
        include
        for target in get_targets(debug=False, paths=paths, fail_on_missing=False)
        for section in target.sections
        for include in section.includes
    )
    includes |= set(
        include
        for target in get_targets(debug=True, paths=paths, fail_on_missing=False)
        for section in target.sections
        for include in section.includes
    )

    latex_files = set()
    for item in paths.working_dir.glob("**/*.tex"):
        try:
            item.relative_to(paths.build_dir)
        except ValueError:
            latex_files.add(str(item.relative_to(paths.working_dir).with_suffix("")))

    for extra in latex_files - includes:
        _logger.info(f"Removing {extra}")
        Path(extra).with_suffix(".tex").unlink()

    # paths = Paths(".")
    # config = get_config(paths=paths)
