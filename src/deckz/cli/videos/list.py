from pathlib import Path

from . import app


@app.command(name="list")
def list_videos(*, workdir: Path = Path()) -> None:
    """List every registered scene's renders and their state.

    One line per render: its quality stamp (or `-` if never rendered), its
    path under `videos.videos_dir`, and its scene's class name.

    Args:
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...videos import quality, renders, scenes

    settings = GlobalSettings.from_yaml(workdir)
    videos_dir = settings.paths.videos_dir
    for scene in scenes(settings):
        for render in renders(videos_dir, scene):
            state = quality(render.file) if render.file.is_file() else "-"
            print(f"{state}\t{render.file.relative_to(videos_dir)}\t{scene.name}")
