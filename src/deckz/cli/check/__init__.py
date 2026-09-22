from cyclopts import App

from .. import app as _parent_app

app = App(
    name="check",
    help="Static, non-compiling analyses of the repository "
    "(see 'deckz run decks'/'deckz run shared'/'deckz run all' for the "
    "compiling validations).",
)
_parent_app.command(app)
