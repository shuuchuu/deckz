from cyclopts import App

from .. import app as _parent_app

app = App(name="print", help="Print resolved settings or variables.")
_parent_app.command(app)
