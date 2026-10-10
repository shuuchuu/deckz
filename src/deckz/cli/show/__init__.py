from cyclopts import App

from .. import app as _parent_app
from .._groups import EVERYDAY

app = App(
    group=EVERYDAY,
    name="show",
    help="Show the resolved deck tree, settings, variables, or paths. "
    "Runs 'tree' when no subcommand is given.",
)
_parent_app.command(app)
