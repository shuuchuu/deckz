from argparse import ArgumentParser
from logging import getLogger
from shutil import copy as shutil_copy

from deckz.cli import register_command
from deckz.paths import Paths
from deckz.targets import Dependencies, Targets


def _parser_definer(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--deck-path",
        dest="paths",
        type=Paths,
        default=".",
        help="Path of the deck, defaults to `%(default)s`.",
    )


@register_command(parser_definer=_parser_definer)
def fill(paths: Paths) -> None:
    """Fill the dependency directories with templates for missing targets."""
    logger = getLogger(__name__)
    if paths.targets.exists():
        if paths.targets_debug.exists():
            dependencies = Dependencies.merge(
                Targets(
                    paths=paths, debug=False, fail_on_missing=False, whitelist=[]
                ).get_dependencies(),
                Targets(
                    paths=paths, debug=True, fail_on_missing=False, whitelist=[]
                ).get_dependencies(),
            )
        else:
            dependencies = Targets(
                paths=paths, debug=False, fail_on_missing=False, whitelist=[]
            ).get_dependencies()
    elif paths.targets_debug.exists():
        dependencies = Targets(
            paths=paths, debug=True, fail_on_missing=False, whitelist=[]
        ).get_dependencies()
    else:
        logger.critical("Could not find any target file.")
        exit(1)
    if dependencies.missing:
        logger.info(
            "Creating the following missing dependencies:\n%s",
            "\n".join(f"  - {str(d)}" for d in sorted(dependencies.missing)),
        )
        for dependency in dependencies.missing:
            dependency.parent.mkdir(exist_ok=True, parents=True)
            shutil_copy(str(paths.template_latex), str(dependency))
    else:
        logger.info("All targets have a matching LaTeX files")
