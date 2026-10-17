from pathlib import Path

from . import app


@app.command(name="list")
def list_videos(*, json: bool = False, workdir: Path = Path()) -> None:
    """List every registered scene's renders and their state.

    One line per render: its quality stamp (or `-` if never rendered), its
    path under `videos.videos_dir`, its scene's class name, and its state:
    `missing` (never rendered), `stale` (its scene changed since), `draft`
    (up to date, at another quality than `videos.published_quality`, which
    `deckz videos publish` refuses) or `fresh`.

    Args:
        json: Print one JSON object instead: `published_quality`, and
            `renders`, each with its `video`, `scene`, `module` and `line`,
            `sources` (what its stamp covers), `language` (null for a scene
            with no on-screen text), `file`, `poster`, `quality` and
            `state`; paths relative to the repository
        workdir: Path to move into before running the command

    """
    import json as json_module

    from ...configuring.settings import GlobalSettings
    from ...videos import quality, renders, scenes, state

    settings = GlobalSettings.from_yaml(workdir)
    git_dir = settings.paths.git_dir
    videos_dir = settings.paths.videos_dir
    wanted = settings.videos.published_quality
    found = [
        (render, state(render, wanted))
        for scene in scenes(settings)
        for render in renders(videos_dir, scene)
    ]
    if not json:
        for render, current in found:
            rendered = quality(render.file) if render.file.is_file() else "-"
            print(
                f"{rendered}\t{render.file.relative_to(videos_dir)}"
                f"\t{render.scene.name}\t{current}"
            )
        return

    def relative(path: Path) -> str:
        return path.relative_to(git_dir).as_posix()

    print(
        json_module.dumps(
            {
                "published_quality": wanted,
                "renders": [
                    {
                        "video": render.scene.video,
                        "scene": render.scene.name,
                        "module": relative(render.scene.module),
                        "line": render.scene.line,
                        "sources": [relative(s) for s in render.scene.sources()],
                        "language": render.language,
                        "file": relative(render.file),
                        "poster": relative(render.file.with_suffix(".png")),
                        "quality": quality(render.file)
                        if render.file.is_file()
                        else None,
                        "state": current,
                    }
                    for render, current in found
                ],
            },
            indent=2,
        )
    )
