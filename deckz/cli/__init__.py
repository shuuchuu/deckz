from functools import partial, wraps
from importlib import import_module, invalidate_caches as importlib_invalidate_caches
from logging import INFO
from pkgutil import walk_packages
from typing import Any, Callable, List, Tuple

from click import (
    argument,
    ClickException,
    group,
    option as click_option,
    Path as ClickPath,
)
from coloredlogs import install as coloredlogs_install

from deckz.exceptions import DeckzException
from deckz.paths import Paths
from deckz.targets import Targets


option = partial(click_option, show_default=True)


deck_path_option = option(
    "--deck-path",
    type=ClickPath(exists=True, readable=True, file_okay=False),
    default=".",
    help="Path of the deck.",
)


def presentation_option(
    default: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    return option(
        "--presentation/--no-presentation",
        "build_presentation",
        default=default,
        help="Compile the presentation version.",
    )


def handout_option(
    default: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    return option(
        "--handout/--no-handout",
        "build_handout",
        default=default,
        help="Compile the handout version.",
    )


def print_option(
    default: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    return option(
        "--print/--no-print",
        "build_print",
        default=default,
        help="Compile the printable version.",
    )


def compile_type_options(
    default_presentation: bool = True,
    default_handout: bool = True,
    default_print: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def inner(f: Callable[..., Any]) -> Callable[..., Any]:
        return print_option(default=default_print)(
            presentation_option(default=default_presentation)(
                handout_option(default=default_handout)(f)
            )
        )

    return inner


def _autocomplete_target_whitelist(
    ctx: Any, args: List[str], incomplete: str
) -> List[Tuple[str, str]]:
    try:
        paths = Paths(".")
        targets = Targets(paths=paths, fail_on_missing=False, whitelist=[])
        return [(t.name, t.title) for t in targets if incomplete in t.name]
    except Exception:
        return []


target_whitelist_argument = argument(
    "target_whitelist",
    metavar="targets",
    nargs=-1,
    autocompletion=_autocomplete_target_whitelist,  # type: ignore
)


@group(chain=True)
def cli() -> None:
    coloredlogs_install(
        level=INFO, fmt="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S",
    )


def command(f: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            result = f(*args, **kwargs)
        except DeckzException as e:
            raise ClickException(str(e)) from e
        return result

    return cli.command()(wrapper)


def _import_module_and_submodules(package_name: str) -> None:
    """
    From https://github.com/allenai/allennlp/blob/master/allennlp/common/util.py
    """
    importlib_invalidate_caches()

    module = import_module(package_name)
    path = getattr(module, "__path__", [])
    path_string = "" if not path else path[0]

    for module_finder, name, _ in walk_packages(path):
        if path_string and module_finder.path != path_string:
            continue
        subpackage = f"{package_name}.{name}"
        _import_module_and_submodules(subpackage)


_import_module_and_submodules(__name__)
