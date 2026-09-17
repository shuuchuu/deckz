from cyclopts import App

from .. import app as _parent_app

app = App(name="extras", help="Side commands unrelated to deck building.")
_parent_app.command(app)
