from pathlib import Path
from typing import TYPE_CHECKING

from . import app

if TYPE_CHECKING:
    from ...configuring.settings import GlobalSettings
    from ...videos import Scene


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
    from ...remotes import publish_remotes, require_remotes
    from ...videos import publish as publish_videos
    from ...videos import publishable, scenes

    settings = GlobalSettings.from_yaml(workdir)
    require_remotes(settings, publish_remotes(settings, "videos"))
    videos_settings = settings.videos
    found = scenes(settings)
    _refuse_other_sources(settings, found)
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


def _refuse_other_sources(settings: "GlobalSettings", found: "list[Scene]") -> None:
    # The scenes' sources here must be the upstream's, for its renders.
    from ...exceptions import VideoPublishRefusedError
    from ...upstream import missing, source, unpushed
    from ...videos.publishing import differing_sources

    git_dir = settings.paths.git_dir
    found_source = source(git_dir)
    if found_source.upstream is None:
        return
    differ = differing_sources(
        git_dir, settings.paths.scenes_dir, found, found_source.commit
    )
    if not differ:
        return
    shown = ", ".join(differ[:8]) + (
        f" and {len(differ) - 8} more" if len(differ) > 8 else ""
    )
    fixes = []
    if commits := unpushed(git_dir, found_source.commit, differ):
        fixes.append(f"push this checkout's {len(commits)} commit(s) changing them")
    if commits := missing(git_dir, found_source.commit, differ):
        fixes.append(
            f"update this checkout to {found_source.name} ({len(commits)} "
            "commit(s) changing them; studioz: Mettre à jour)"
        )
    if not fixes:
        fixes.append("commit and push this checkout's changes to them")
    msg = (
        f"the scenes' sources here differ from {found_source.name}'s: {shown}. "
        f"Renders fresh here wouldn't be {found_source.name}'s: "
        + ", then ".join(fixes)
        + ", render what that makes stale (`deckz videos render`), and publish "
        "again"
    )
    raise VideoPublishRefusedError(msg)
