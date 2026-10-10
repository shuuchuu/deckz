from cyclopts import App

from .. import app as _parent_app
from .._groups import TRANSLATION

app = App(group=TRANSLATION, name="i18n", help="Check fr/en translation coverage.")
_parent_app.command(app)
