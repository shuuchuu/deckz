from cyclopts import App

from .. import app as _parent_app

app = App(name="clean", help="Wipe build directories, or unused LaTeX files.")
_parent_app.command(app)
