from cyclopts import App

from .. import app as _parent_app

app = App(
    name="gpu",
    help="Run lab notebooks on a rented GPU machine, the way Colab runs them "
    "(Colab's image, its CPU count, peak RAM recorded): up, queue, run, "
    "status, fetch, report, down; several machines at once with --machine. "
    "Needs `deckz[gpu]` and a Vast.ai API key (`vastai set api-key`). A "
    "machine bills until `down`.",
)
_parent_app.command(app)
