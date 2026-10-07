from pathlib import Path

from . import app


@app.command()
def publish(*, break_published_links: bool = False, workdir: Path = Path()) -> None:
    """Replace the videos remote's branch with one commit of every scene's renders.

    Refuses to publish if `videos.scenes_dir` has uncommitted changes, a
    render is missing/stale/at the wrong quality (run `deckz videos
    render` first), one is over the publish size limit, or doing so would
    drop an already-published render's path.

    Args:
        break_published_links: Allow removing an already-published
            render's path
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...videos import publish as publish_videos
    from ...videos import publishable, scenes

    settings = GlobalSettings.from_yaml(workdir)
    videos_settings = settings.videos
    found = scenes(settings)
    preview = publishable(
        found,
        settings.paths.videos_dir,
        quality=videos_settings.published_quality,
        max_size=videos_settings.max_publish_size_mb * 1_000_000,
        warn_size=videos_settings.warn_publish_size_mb * 1_000_000,
    )
    for warning in preview.warnings:
        print(f"warning: {warning}")
    published = publish_videos(
        settings.paths.git_dir,
        settings.paths.scenes_dir,
        preview,
        remote=videos_settings.publish_remote,
        branch=videos_settings.publish_branch,
        break_published_links=break_published_links,
    )
    print(
        "Published."
        if published
        else f"{videos_settings.publish_remote} is already up to date."
    )
