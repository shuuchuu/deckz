from cyclopts import App

from .. import app as _parent_app
from .._groups import SETUP

app = App(
    group=SETUP,
    name="worktree",
    help="Work in a separate checkout of the repository (a git worktree), "
    "builds included.",
)
_parent_app.command(app)
