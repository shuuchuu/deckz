from cyclopts import App

from .. import app as _parent_app
from .._groups import NEW

app = App(
    group=NEW,
    name="new",
    help="Create the files of a new deck or shared section, in both languages.",
)
_parent_app.command(app)
