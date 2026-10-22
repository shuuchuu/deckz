from pathlib import Path
from sys import exit as sys_exit

from . import app


@app.command()
def fetch(*, source: str | None = None, workdir: Path = Path()) -> None:
    """Put the published renders in place of the videos never rendered here.

    For a checkout without Manim, or a CI job building decks: each render
    missing from the videos directory is downloaded from the published
    branch, with its poster frame (needs `ffmpeg`). A render already there
    is never replaced. A fetched render carries no sources stamp, so `deckz
    videos render` renders it again. A video never published is listed
    (only a deck showing it fails to build); exits 1 when a render got no
    poster.

    Args:
        source: The git remote or repository URL to fetch the renders from,
            instead of `videos.publish_remote` (e.g. a CI job's
            `https://github.com/<owner>/<videos>`)
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...videos import scenes
    from ...videos.publishing import fetch_renders

    settings = GlobalSettings.from_yaml(workdir)
    videos = settings.videos
    result = fetch_renders(
        settings.paths.git_dir,
        settings.paths.videos_dir,
        scenes(settings),
        source=source or videos.publish_remote,
        branch=videos.publish_branch,
        quality=videos.published_quality,
    )
    git_dir = settings.paths.git_dir
    for file in result.fetched:
        print(f"fetched {file.relative_to(git_dir)}")
    for path in result.unpublished:
        print(f"{path}: never published: `deckz videos render` renders it")
    for problem in result.failed:
        print(problem)
    if not (result.fetched or result.unpublished or result.failed):
        print("every video has a render")
    if result.failed:
        sys_exit(1)
