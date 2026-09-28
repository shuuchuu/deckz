from collections.abc import Iterable
from logging import DEBUG, INFO, WARNING, basicConfig, getLogger
from os import environ
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console
from rich.logging import RichHandler

from .. import __version__
from ..exceptions import DeckParsingError, DeckzError

app = App(version=__version__)
app.register_install_completion_command()


def main(args: Iterable[str] | None = None) -> None:
    """Run the deckz CLI.

    Exit codes: 0 on success, 1 on a deckz error (a user error such as a \
    missing flavor or a failed compile, reported without a traceback) or on \
    `deckz check variables` findings, 2 on a command-line usage error. Pass \
    `--debug` (or set `DECKZ_DEBUG=1`) to get the traceback of a deckz error \
    instead.

    Args:
        args: Command-line arguments, defaults to `sys.argv[1:]`.

    Raises:
        SystemExit: With code 2 on a command-line usage error.
    """
    from cyclopts import CycloptsError

    from ..utils import import_module_and_submodules

    import_module_and_submodules(__name__)
    try:
        app.meta(args, result_action="return_none", exit_on_error=False)
    except CycloptsError:
        # Already printed by cyclopts.
        raise SystemExit(2) from None


@app.meta.default
def _launch(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    verbose: Annotated[bool, Parameter(name=["--verbose", "-v"], negative="")] = False,
    quiet: Annotated[bool, Parameter(name=["--quiet", "-q"], negative="")] = False,
    debug: Annotated[bool, Parameter(negative="")] = False,
) -> None:
    """Manage slide decks sharing sections, compiled with Typst.

    Args:
        tokens: The command and its arguments.
        verbose: Also log details, e.g. timings and why fragments are rebuilt
        quiet: Only log warnings and errors
        debug: Like --verbose, and show the traceback of a deckz error

    Raises:
        DeckzError: Only with `--debug` or when `DECKZ_DEBUG` is set.
        SystemExit: With code 1 on a deckz error.
    """
    # Diagnostics go to stderr, leaving stdout to results (e.g. --json).
    basicConfig(
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            RichHandler(
                console=Console(stderr=True),
                rich_tracebacks=True,
                tracebacks_show_locals=False,
            )
        ],
    )
    # Set apart from basicConfig, which is a no-op once the root logger has
    # handlers, e.g. on a second `main` call in the same process.
    getLogger().setLevel(DEBUG if verbose or debug else WARNING if quiet else INFO)
    try:
        app(tokens, result_action="return_none", exit_on_error=False)
    except DeckzError as e:
        if debug or environ.get("DECKZ_DEBUG"):
            raise
        if isinstance(e, DeckParsingError):
            from ._presentation import render_parse_errors

            render_parse_errors(e.deck)
            getLogger(__name__).error("deck parsing failed, see the tree above")
        else:
            getLogger(__name__).error(str(e))
        raise SystemExit(1) from None
