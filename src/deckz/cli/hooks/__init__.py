from cyclopts import App

from .. import app as _parent_app

app = App(
    name="hooks",
    help="Install deckz's git hooks (pre-commit, commit-msg) into the "
    "current repository.",
)
_parent_app.command(app)
