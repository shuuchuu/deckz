from cyclopts import App

from .. import app as _parent_app

app = App(name="i18n", help="Check and maintain fr/en translation parity.")
_parent_app.command(app)
