from cyclopts import App

from .. import app as _parent_app
from .._groups import MAINTENANCE

app = App(
    group=MAINTENANCE, name="flavor", help="Rename or deduplicate sections' flavors."
)
_parent_app.command(app)
