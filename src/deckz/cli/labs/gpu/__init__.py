from typing import Annotated

from cyclopts import App, Parameter

from .. import app as _parent_app

Gpus = Annotated[list[str] | None, Parameter(consume_multiple=True, negative="")]
"""GPU names in order of preference: `--gpu A B`, or `--gpu A --gpu B`."""

app = App(
    name="gpu",
    help="Run lab notebooks on a rented GPU machine, the way Colab runs them "
    "(Colab's image, its CPU count, peak RAM recorded): pass, which rents a "
    "machine, runs the notebooks and destroys it, or each step: up, queue, "
    "run, status, fetch, report, down; several machines at once with --machine. "
    "Needs `deckz[gpu]` and a Vast.ai API key (`vastai set api-key`). A "
    "machine bills until `down`.",
)
_parent_app.command(app)
