"""Render and publish `@register_scene` Manim videos (`deckz videos`, `deckz[videos]`).

A scene is a Manim `Scene` subclass decorated `@register_scene`
(`deckz.videos.register_scene`) in a `.py` file under
`GlobalPaths.scenes_dir` (default `figures/scenes`). Rendering shells out
to `manim`/`ffmpeg` as subprocesses (see `rendering`); scene discovery
itself (`scenes`) never imports Manim, so listing or checking scenes needs
no extra dependency.
"""

from .publishing import (
    PublishPreview,
    fetch_published,
    publish,
    publishable,
    published_blobs,
    site_path,
    unpublished_reason,
)
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
    "fetch_published",
    "out_of_date",
    "publish",
    "publishable",
    "published_blobs",
    "quality",
    "register_scene",
    "render_all",
    "renders",
    "scenes",
    "site_path",
    "unpublished_reason",
    "video_file",
]
