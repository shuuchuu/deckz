from pathlib import Path

from . import app


@app.command()
def publish(*, break_published_links: bool = False, workdir: Path = Path()) -> None:
    """Replace the videos remote's branch with one commit of every scene's renders.

    The renders are this checkout's, which must be those of the main
    checkout's upstream branch (`origin/main`), fetched first: a render is
    fresh for the sources it was made from, so the scenes' sources here
    must be the upstream's (update this checkout, push its commits). A
    repository with no upstream publishes this checkout's renders as they
    are.

    Refuses to publish if the scenes' sources differ from the upstream's,
    `videos.scenes_dir` has uncommitted changes, a
    render is missing/stale/at the wrong quality (run `deckz videos
    render` first), one is over the publish size limit, or doing so would
    drop an already-published render's path. A missing remote, one that
    can't be reached or refuses the push fails with git's message and the
    fix (`setup.remotes` gives `deckz setup` the remotes to add).

    Args:
        break_published_links: Allow removing an already-published
            render's path
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...publishing import publish_videos, videos_preview

    settings = GlobalSettings.from_yaml(workdir)
    preview = videos_preview(settings)
    for warning in preview.warnings:
        print(f"warning: {warning}")
    published = publish_videos(
        settings, preview, break_published_links=break_published_links
    )
    print(
        "Published."
        if published
        else f"{settings.videos.publish_remote} is already up to date."
    )
