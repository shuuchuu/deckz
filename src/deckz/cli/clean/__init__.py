from cyclopts import App

from .. import app as _parent_app
from .._groups import MAINTENANCE

app = App(
    group=MAINTENANCE,
    name="clean",
    help="Wipe build directories. Runs 'deck' when no subcommand is given.",
)
_parent_app.command(app)
