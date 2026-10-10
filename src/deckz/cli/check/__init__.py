from cyclopts import App

from .. import app as _parent_app
from .._groups import EVERYDAY

app = App(
    group=EVERYDAY,
    name="check",
    help="Static, non-compiling analyses of the repository "
    "(see 'deckz run decks'/'deckz run shared'/'deckz run all' for the "
    "compiling validations). Runs 'content' when no subcommand is given.",
)
_parent_app.command(app)
