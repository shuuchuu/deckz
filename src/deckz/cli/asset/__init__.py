from cyclopts import App

from .. import app as _parent_app
from .._groups import CONTENT

app = App(group=CONTENT, name="asset", help="Inspect assets used by shared sections.")
_parent_app.command(app)
