from collections.abc import Iterable
from logging import DEBUG, INFO, WARNING, basicConfig, getLogger
from os import environ
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console
from rich.logging import RichHandler

from .. import __version__
from ..exceptions import DeckParsingError, DeckzError

# Ctrl-C is handled by `_launch`, which needs the KeyboardInterrupt that
# cyclopts would otherwise turn into a bare `sys.exit(130)`.
app = App(version=__version__, suppress_keyboard_interrupt=False)
app.meta.suppress_keyboard_interrupt = False
app.register_install_completion_command()


def main(args: Iterable[str] | None = None) -> None:
    """Run the deckz CLI.

    Exit codes: 0 on success, 1 on a deckz error (a user error such as a
    missing flavor or a failed compile, reported without a traceback) or on
    `deckz check variables` findings, 2 on a command-line usage error. Pass
    `--debug` (or set `DECKZ_DEBUG=1`) to get the traceback of a deckz error
    instead.

    Environment variables (e.g. `DECKZ_LANG`, `DECKZ_RUN_PRINT`) are also
    read from the closest `.env` file, looked up from the current directory
    upwards. Variables already set in the environment take precedence.

    Args:
        args: Command-line arguments, defaults to `sys.argv[1:]`.

    Raises:
        SystemExit: With code 2 on a command-line usage error.
    """
    from cyclopts import CycloptsError
    from dotenv import find_dotenv, load_dotenv

    from ..utils import import_module_and_submodules

    # `usecwd`: without it, the lookup starts from deckz's own installed code.
    load_dotenv(find_dotenv(usecwd=True))
    import_module_and_submodules(__name__)
    try:
        app.meta(args, result_action="return_none", exit_on_error=False)
    except CycloptsError:
        # Already printed by cyclopts.
        raise SystemExit(2) from None


def _stop_child_processes() -> None:
    # Typst workers and multiprocessing pools, so that a Ctrl-C'd build stops
    # at once instead of waiting for the compilations already running.
    from multiprocessing import active_children
    from signal import SIG_IGN, SIGINT, signal

    from ..components import compiler

    # A repeated Ctrl-C (or one forwarded again by a wrapper such as `uv run`)
    # must not interrupt this cleanup, or the exit-time join of the build's
    # threads, with a traceback.
    signal(SIGINT, SIG_IGN)
    compiler.stop()

    for child in active_children():
        child.kill()
        child.join(timeout=5)


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
        KeyboardInterrupt: On Ctrl-C, only with `--debug` or `DECKZ_DEBUG`.
        SystemExit: With code 1 on a deckz error, 130 on Ctrl-C.
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
    except KeyboardInterrupt:
        if debug or environ.get("DECKZ_DEBUG"):
            raise
        _stop_child_processes()
        getLogger(__name__).error("Interrupted")
        # 128 + SIGINT, what a shell reports for a process killed by Ctrl-C.
        raise SystemExit(130) from None
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
