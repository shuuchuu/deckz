from logging import INFO, basicConfig
from pathlib import Path
from typing import Any, Callable, TypeVar

from click import group
from click import option as click_option
from rich.logging import RichHandler

from deckz.utils import import_module_and_submodules

_T = TypeVar("_T", bound=Callable[..., Any])


def option(*args: Any, **kwargs: Any) -> Callable[[_T], _T]:
    return click_option(*args, show_default=True, **kwargs)


@group(context_settings=dict(default_map=dict(show_default=True)))
def app() -> None:
    """Handle a large number of beamer decks, used by several persons."""
    pass


def option_workdir(command: _T) -> _T:
    return option(
        "--workdir",
        type=Path,
        default=Path("."),
        help="Path to move into before running the command",
    )(command)


def options_output(
    handout: bool, presentation: bool, print: bool
) -> Callable[[_T], _T]:
    def f(command: _T) -> _T:
        return option(
            "--handout/--no-handout",
            default=handout,
            help="Produce PDFs without animations",
        )(
            option(
                "--presentation/--no-presentation",
                default=presentation,
                help="Produce PDFs with animations",
            )(
                option(
                    "--print/--no-print", default=print, help="Produce printable PDFs"
                )(command)
            )
        )

    return f


def main() -> None:
    basicConfig(
        level=INFO,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True, tracebacks_show_locals=False)],
    )
    import_module_and_submodules(__name__)
    app()
