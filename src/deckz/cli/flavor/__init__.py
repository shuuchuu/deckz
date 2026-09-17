from cyclopts import App

from .. import app as _parent_app

app = App(name="flavor", help="Rename or deduplicate sections' flavors.")
_parent_app.command(app)
