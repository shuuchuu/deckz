from pathlib import Path
from sys import exit as sys_exit

from . import app


@app.command()
def render(
    scene: str | None = None,
    /,
    *,
    quality: str | None = None,
    force: bool = False,
    workdir: Path = Path(),
) -> None:
    """Render the registered scenes that are out of date into videos.

    Only the renders missing, older than their scene's module, or at
    another quality than QUALITY are rendered (in parallel), unless
    --force. Needs the `deckz[videos]` extra (Manim) and `ffmpeg`.

    Args:
        scene: Only render this video (its path, as `deckz videos list`
            prints it, or its class name), instead of every scene
        quality: Manim quality flag (`l` to `k`), defaulting to
            `videos.published_quality`
        force: Render even the videos that look up to date
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...videos import out_of_date, renders, scenes
    from ...videos.rendering import render_all
    from .._presentation import RichProgress

    settings = GlobalSettings.from_yaml(workdir)
    wanted_quality = quality or settings.videos.published_quality
    found = scenes(settings)
    if scene:
        found = [s for s in found if scene in (s.video, s.name)]
        if not found:
            print(f"no scene {scene!r} (see `deckz videos list`)")
            sys_exit(2)
    to_render = [
        r
        for s in found
        for r in renders(settings.paths.videos_dir, s)
        if force or out_of_date(r, wanted_quality)
    ]
    if not to_render:
        print("every video is up to date")
        return
    failed = render_all(
        to_render, wanted_quality, settings.paths.scenes_dir, RichProgress()
    )
    if failed:
        print("failed to render:", *failed, sep="\n")
        sys_exit(1)
