from argparse import ArgumentParser
from logging import getLogger
from os.path import join as path_join
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set

from deckz.builder import build
from deckz.config import get_config
from deckz.paths import Paths
from deckz.targets import get_targets


_logger = getLogger(__name__)


class Command(NamedTuple):
    name: str
    description: str
    handler: Callable[..., Any]
    parser_definer: Callable[[ArgumentParser], None]


commands: List[Command] = []


def register_command(
    parser_definer: Callable[[ArgumentParser], None] = lambda _: None,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def wrapper(handler: Callable[..., Any]) -> Callable[..., Any]:
        commands.append(
            Command(
                name=handler.__name__.replace("_", "-") if name is None else name,
                description=handler.__doc__.strip().splitlines()[0]
                if description is None
                else description,
                parser_definer=parser_definer,
                handler=handler,
            )
        )
        return handler

    return wrapper


def _define_run_parser(parser: ArgumentParser) -> None:
    parser.add_argument(
        "targets",
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


@register_command(parser_definer=_define_run_parser)
def run(
    targets: List[str], handout: bool, presentation: bool, verbose_latexmk: bool
) -> None:
    """Compile main targets."""
    _run(
        handout=handout,
        presentation=presentation,
        verbose_latexmk=verbose_latexmk,
        debug=False,
        target_whitelist=targets,
    )


def _define_debug_parser(parser: ArgumentParser) -> None:
    parser.add_argument(
        "targets",
        nargs="*",
        help="Targets to restrict to. No argument = consider everything.",
    )
    parser.add_argument(
        "--handout", action="store_true", help="Compile the handout.",
    )
    parser.add_argument(
        "--no-presentation",
        dest="presentation",
        action="store_false",
        help="Don't compile the presentation.",
    )
    parser.add_argument(
        "--silent-latexmk",
        dest="verbose_latexmk",
        action="store_false",
        help="Make latexmk silent.",
    )


@register_command(parser_definer=_define_debug_parser)
def debug(
    targets: List[str], handout: bool, presentation: bool, verbose_latexmk: bool
) -> None:
    """Compile debug targets."""
    _run(
        handout=handout,
        presentation=presentation,
        verbose_latexmk=verbose_latexmk,
        debug=True,
        target_whitelist=targets if targets else None,
    )


def _run(
    handout: bool,
    presentation: bool,
    verbose_latexmk: bool,
    debug: bool,
    target_whitelist: List[str],
) -> None:
    paths = Paths(".")
    config = get_config(paths=paths)
    targets = get_targets(
        debug=debug, paths=paths, fail_on_missing=True, whitelist=target_whitelist,
    )
    for i, target in enumerate(targets, start=1):
        if handout:
            _logger.info(f"Building handout for target {i}/{len(targets)}")
            build(
                config=config,
                target=target,
                handout=True,
                verbose_latexmk=verbose_latexmk,
                paths=paths,
            )
        if presentation:
            _logger.info(f"Building presentation for target {i}/{len(targets)}")
            build(
                config=config,
                target=target,
                handout=False,
                verbose_latexmk=verbose_latexmk,
                paths=paths,
            )


@register_command()
def print_config() -> None:
    """Print the resolved configuration."""
    paths = Paths(".")
    config = get_config(paths=paths)
    _logger.info(
        "Resolved config as:\n%s",
        "\n".join((f"  - {k}: {v}") for k, v in config.items()),
    )


@register_command()
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
        path_join(target.name, include)
        for target in get_targets(
            debug=False, paths=paths, fail_on_missing=False, whitelist=[]
        )
        for section in target.sections
        for include in section.includes
    )
    includes |= set(
        path_join(target.name, include)
        for target in get_targets(
            debug=True, paths=paths, fail_on_missing=False, whitelist=[]
        )
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
