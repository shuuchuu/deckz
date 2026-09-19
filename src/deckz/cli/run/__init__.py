from cyclopts import App

from .. import app as _parent_app

app = App(
    name="run",
    help="Compile a deck, a single file, or a section flavor. "
    "Runs 'deck' when no subcommand is given.",
)
_parent_app.command(app)
