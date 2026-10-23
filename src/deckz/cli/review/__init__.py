from cyclopts import App

from .. import app as _parent_app
from .._groups import CONTENT

app = App(
    group=CONTENT,
    name="review",
    help="Know which version of each file was reviewed, and what changed since "
    "(the reports under `review.dir`).",
)
_parent_app.command(app)
