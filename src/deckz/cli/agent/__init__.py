from cyclopts import App

from .. import app as _parent_app
from .._groups import MAINTENANCE

app = App(
    group=MAINTENANCE,
    name="agent",
    help="Run unattended Claude Code sessions (`claude -p`) on the repository.",
)
_parent_app.command(app)
