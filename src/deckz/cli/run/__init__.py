from cyclopts import App

from .. import app as _parent_app

app = App(
    name="run",
    help="Compile a deck, a single file, a section flavor, project assets, or "
    "validate the whole repository ('decks'/'shared'/'all'). Add --watch to "
    "recompile on file changes instead of compiling once. Runs 'deck' when "
    "no subcommand is given.",
)
_parent_app.command(app)
