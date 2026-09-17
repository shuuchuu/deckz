from cyclopts import App

from .. import app as _parent_app

app = App(name="asset", help="Inspect assets used by shared sections.")
_parent_app.command(app)
