from cyclopts import App

from .. import app as _parent_app

app = App(
    name="show", help="Show the resolved deck tree, settings, variables, or paths."
)
_parent_app.command(app)
