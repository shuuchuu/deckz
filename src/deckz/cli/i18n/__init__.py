from cyclopts import App

from .. import app as _parent_app

app = App(name="i18n", help="Check fr/en translation coverage.")
_parent_app.command(app)
