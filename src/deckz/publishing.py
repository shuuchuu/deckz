"""Publish the labs and the videos: `deckz labs publish`, `deckz videos publish`.

Both publish what the main checkout's upstream branch holds (`origin/main`),
whichever checkout they run in (`deckz.upstream`), and refuse what would put
older or unchecked files in place of the published ones. `deckz push
--publish` runs them after its pushes, when `deckz status` finds something
left to publish (`deckz.status.unpublished`).
"""

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .configuring.settings import GlobalSettings
    from .upstream import Source
    from .videos import Scene
    from .videos.publishing import PublishPreview


def publish_labs(
    settings: "GlobalSettings",
    *,
    break_published_links: bool = False,
    replace_unknown: bool = False,
    skip_checks: bool = False,
) -> tuple[bool, "Source"]:
    """Replace the labs remote's branch with one commit of the upstream's notebooks.

    See `deckz labs publish --help` for what is published and refused.

    Args:
        settings: The repository's settings.
        break_published_links: Allow removing an already-published notebook's \
            link.
        replace_unknown: Allow replacing a published version the upstream's \
            history doesn't hold.
        skip_checks: Don't run the content checks.

    Returns:
        Whether anything was published, and what it was taken from.

    Raises:
        LabPublishRefusedError: If the labs have commits the upstream branch \
            lacks, or the checks report a problem in a notebook, without \
            `skip_checks`.
    """
    from pathlib import PurePosixPath

    from .checking import export_tree
    from .components.factory import GlobalSettingsFactory
    from .configuring.settings import GlobalSettings
    from .exceptions import LabPublishRefusedError
    from .labs.publishing import publish as publish_notebooks
    from .remotes import publish_remotes, require_remotes
    from .upstream import source, unpushed

    git_dir = settings.paths.git_dir
    require_remotes(settings, publish_remotes(settings, "labs"))
    paths = [settings.paths.labs_notebooks_dir.relative_to(git_dir).as_posix()]
    if settings.paths.labs_published_dir is not None:
        paths.append(settings.paths.labs_published_dir.relative_to(git_dir).as_posix())
    found_source = source(git_dir)
    if commits := unpushed(git_dir, found_source.commit, paths):
        listed = "\n".join(f"  {commit}" for commit in commits)
        msg = (
            f"these commits change the labs and aren't on {found_source.name} "
            f"yet:\n{listed}\nPush them first: a publish takes "
            f"{found_source.name}'s notebooks"
        )
        raise LabPublishRefusedError(msg)
    if not skip_checks:
        checked = settings
        if any(
            _tree(git_dir, f"HEAD:{path}")
            != _tree(git_dir, f"{found_source.commit}:{path}")
            for path in paths
        ):
            exported = export_tree(git_dir, found_source.commit, "upstream")
            checked = GlobalSettings.from_yaml(exported, git_dir=exported)
        notebooks = PurePosixPath(paths[0])
        found = [
            finding
            for finding in GlobalSettingsFactory(checked).checks_runner().findings()
            if finding.under(notebooks)
        ]
        if found:
            listed = "\n".join(f"  {f.check}: {f.text}" for f in found)
            msg = (
                f"the content checks report problems in {found_source.name}'s "
                f"notebooks:\n{listed}\nFix them (each says how), commit and "
                "push, or pass --skip-checks to publish them as they are"
            )
            raise LabPublishRefusedError(msg)
    published = publish_notebooks(
        git_dir,
        settings.paths.labs_notebooks_dir,
        published_dir=settings.paths.labs_published_dir,
        id_metadata_key=settings.labs.id_metadata_key,
        id_pattern=settings.labs.id_pattern,
        remote=settings.labs.publish_remote,
        branch=settings.labs.publish_branch,
        files_remote=settings.labs.published_files_remote,
        files_branch=settings.labs.published_files_branch,
        break_published_links=break_published_links,
        replace_unknown=replace_unknown,
        not_secrets=settings.labs.not_secrets,
        source=found_source.commit,
        source_name=found_source.name,
    )
    return published, found_source


def _tree(git_dir: Path, spec: str) -> str:
    # The object `spec` names (`<rev>:<path>`), "" if it names none.
    return subprocess.run(
        ["git", "-C", str(git_dir), "rev-parse", "--verify", "--quiet", spec],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


def videos_preview(settings: "GlobalSettings") -> "PublishPreview":
    """What `publish_videos` would publish, with its warnings (a render's size).

    Raises `VideoPublishRefusedError` if the scenes' sources here differ from \
    the upstream's.

    Returns:
        The preview to pass to `publish_videos`.
    """
    from .remotes import publish_remotes, require_remotes
    from .videos import publishable, scenes

    require_remotes(settings, publish_remotes(settings, "videos"))
    videos_settings = settings.videos
    found = scenes(settings)
    _refuse_other_sources(settings, found)
    return publishable(
        found,
        settings.paths.videos_dir,
        quality=videos_settings.published_quality,
        max_size=videos_settings.max_publish_size_mb * 1_000_000,
        warn_size=videos_settings.warn_publish_size_mb * 1_000_000,
    )


def publish_videos(
    settings: "GlobalSettings",
    preview: "PublishPreview",
    *,
    break_published_links: bool = False,
) -> bool:
    """Replace the videos remote's branch with one commit of every scene's renders.

    See `deckz videos publish --help` for what is published and refused.

    Args:
        settings: The repository's settings.
        preview: What `videos_preview` returned.
        break_published_links: Allow removing an already-published render's path.

    Returns:
        Whether anything was published.
    """
    from .videos import publish

    return publish(
        settings.paths.git_dir,
        settings.paths.scenes_dir,
        preview,
        remote=settings.videos.publish_remote,
        branch=settings.videos.publish_branch,
        break_published_links=break_published_links,
    )


def _refuse_other_sources(settings: "GlobalSettings", found: "list[Scene]") -> None:
    # The scenes' sources here must be the upstream's, for its renders.
    from .exceptions import VideoPublishRefusedError
    from .upstream import missing, source, unpushed
    from .videos.publishing import differing_sources

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
