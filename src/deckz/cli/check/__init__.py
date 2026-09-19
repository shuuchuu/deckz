from cyclopts import App

from .. import app as _parent_app

app = App(
    name="check",
    help="Validate the repository by compiling shared content, or every deck. "
    "No default: 'decks', 'shared', and 'all' have wildly different costs, so "
    "an explicit subcommand is required.",
)
_parent_app.command(app)
