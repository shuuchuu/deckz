from typing import Any

from cyclopts import App

from .. import app as _parent_app
from .._groups import SETUP

app = App(
    group=SETUP,
    name="hooks",
    help="Install deckz's git hooks (pre-commit, commit-msg) and Claude "
    "Code hooks into the current repository.",
)
_parent_app.command(app)


def read_payload() -> dict[str, Any]:
    """The calling Claude Code hook's JSON payload, from stdin.

    Returns:
        The parsed payload, or `{}` if stdin is empty or isn't valid JSON \
        (a hook command must never fail loudly on an unexpected payload).
    """
    from json import JSONDecodeError, loads
    from sys import stdin

    try:
        return loads(stdin.read() or "{}")
    except JSONDecodeError:
        return {}


def report_error(name: str, error: BaseException) -> None:
    """Log `error` to stderr without raising it: a hook bug must never block the action.

    Args:
        name: The hook command's name, e.g. `"pre-bash"`.
        error: The exception caught around the hook's own logic.
    """
    from sys import stderr

    print(f"deckz hooks {name}: {error!r}", file=stderr)
