from cyclopts import App
from cyclopts.config import Env

from .. import app as _parent_app
from .._groups import EVERYDAY

app = App(
    group=EVERYDAY,
    name="run",
    help="Compile a deck, a single file, a section flavor, project assets, or "
    "validate the whole repository ('decks'/'shared'/'all'). Add --watch to "
    "recompile on file changes instead of compiling once. Runs 'deck' when "
    "no subcommand is given. Options default to their environment variable "
    "when set (shown in each command's help, e.g. DECKZ_RUN_PRINT=false), "
    "which a .env file can set.",
    # Not per subcommand (`command=False`): `deckz run` and `deckz run deck`
    # must read the same variables.
    config=Env("DECKZ_RUN_", command=False),
)
_parent_app.command(app)
