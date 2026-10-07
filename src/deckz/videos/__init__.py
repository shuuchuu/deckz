"""Render and publish `@register_scene` Manim videos (`deckz videos`, `deckz[videos]`).

A scene is a Manim `Scene` subclass decorated `@register_scene`
(`deckz.videos.register_scene`) in a `.py` file under
`GlobalPaths.scenes_dir` (default `figures/scenes`). Rendering shells out
to `manim`/`ffmpeg` as subprocesses (see `rendering`); scene discovery
itself (`scenes`) never imports Manim, so listing or checking scenes needs
no extra dependency.
"""

from .publishing import PublishPreview, publish, publishable
from .rendering import render_all
from .scenes import (
    Render,
    Scene,
    out_of_date,
    quality,
    register_scene,
    renders,
    scenes,
    video_file,
)

__all__ = [
    "PublishPreview",
    "Render",
    "Scene",
    "out_of_date",
    "publish",
    "publishable",
    "quality",
    "register_scene",
    "render_all",
    "renders",
    "scenes",
    "video_file",
]
