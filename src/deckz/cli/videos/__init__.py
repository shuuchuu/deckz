from cyclopts import App

from .. import app as _parent_app

app = App(
    name="videos",
    help="Render Manim scenes registered with `deckz.videos.register_scene` "
    "into videos, list them, and publish them.",
)
_parent_app.command(app)
