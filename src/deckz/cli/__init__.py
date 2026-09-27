from collections.abc import Iterable
from logging import INFO, basicConfig, getLogger
from os import environ

from cyclopts import App
from rich.logging import RichHandler

from .. import __version__
from ..exceptions import DeckParsingError, DeckzError

app = App(version=__version__)
app.register_install_completion_command()


def main(args: Iterable[str] | None = None) -> None:
    """Run the deckz CLI.

    Exit codes: 0 on success, 1 on a deckz error (a user error such as a \
    missing flavor or a failed compile, reported without a traceback) or on \
    `deckz check variables` findings, 2 on a command-line usage error. Set \
    `DECKZ_DEBUG=1` to get the traceback of a deckz error instead.

    Args:
        args: Command-line arguments, defaults to `sys.argv[1:]`.

    Raises:
        DeckzError: Only when `DECKZ_DEBUG` is set.
        SystemExit: With code 1 on a deckz error.
    """
    basicConfig(
        level=INFO,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True, tracebacks_show_locals=False)],
    )
    from ..utils import import_module_and_submodules

    import_module_and_submodules(__name__)
    try:
        app(args, result_action="return_none")
    except DeckzError as e:
        if environ.get("DECKZ_DEBUG"):
            raise
        if isinstance(e, DeckParsingError):
            from ._presentation import render_parse_errors

            render_parse_errors(e.deck)
            getLogger(__name__).error("deck parsing failed, see the tree above")
        else:
            getLogger(__name__).error(str(e))
        raise SystemExit(1) from None
