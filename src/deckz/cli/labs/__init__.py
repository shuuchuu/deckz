from cyclopts import App

from .. import app as _parent_app
from .._groups import LABS_VIDEOS

app = App(
    group=LABS_VIDEOS,
    name="labs",
    help="Manage lab notebooks: normalize their Colab metadata, reformat "
    "them canonically, assign IDs, check/compare/dump them, write back "
    "executed outputs, and publish them.",
)
_parent_app.command(app)
