from cyclopts import App

from .. import app as _parent_app
from .._groups import MAINTENANCE

app = App(
    group=MAINTENANCE, name="extras", help="Side commands unrelated to deck building."
)
_parent_app.command(app)
