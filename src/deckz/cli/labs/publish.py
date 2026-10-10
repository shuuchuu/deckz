from pathlib import Path

from . import app


@app.command()
def publish(*, break_published_links: bool = False, workdir: Path = Path()) -> None:
    """Replace the labs remote's branch with one commit of HEAD's lab notebooks.

    Refuses to publish if the notebooks directory has uncommitted changes,
    a committed notebook has no valid or unique ID (run `deckz labs ids`
    first) or holds what looks like a credential (see the `lab-secrets`
    check), or doing so would drop an already-published notebook's name.

    Args:
        break_published_links: Allow removing an already-published
            notebook's link
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...labs.publishing import publish as publish_labs

    settings = GlobalSettings.from_yaml(workdir)
    published = publish_labs(
        settings.paths.git_dir,
        settings.paths.labs_notebooks_dir,
        id_metadata_key=settings.labs.id_metadata_key,
        id_pattern=settings.labs.id_pattern,
        remote=settings.labs.publish_remote,
        branch=settings.labs.publish_branch,
        break_published_links=break_published_links,
        not_secrets=settings.labs.not_secrets,
    )
    print(
        "Published."
        if published
        else f"{settings.labs.publish_remote} is already up to date."
    )
