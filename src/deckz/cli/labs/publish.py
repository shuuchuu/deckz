from pathlib import Path

from . import app


@app.command()
def publish(
    *,
    break_published_links: bool = False,
    skip_checks: bool = False,
    workdir: Path = Path(),
) -> None:
    """Replace the labs remote's branch with one commit of HEAD's lab notebooks.

    The files committed under `labs/published/` (`paths.labs_published_dir`)
    are published too, at the same paths: in the same commit, or, when
    `labs.published_files_remote` is set, in a commit of their own that
    replaces that remote's branch (e.g. the repository a Codespace opens).

    Refuses to publish if either directory has uncommitted changes, a
    committed notebook has no valid or unique ID (run `deckz labs ids`
    first) or holds what looks like a credential (see the `lab-secrets`
    check), the content checks report a problem in a notebook (deferred
    ones included: `lab-pairs`, `lab-format`, `lab-outputs`..., which let a
    commit through but not the notebooks going public), or doing so would
    drop an already-published notebook's name.

    Args:
        break_published_links: Allow removing an already-published
            notebook's link
        skip_checks: Don't run the content checks: publish whatever they
            would report, but a credential, still refused
        workdir: Path to move into before running the command

    Raises:
        LabPublishRefusedError: If the checks report a problem in a \
            notebook, without --skip-checks.

    """
    from pathlib import PurePosixPath

    from ...components.factory import GlobalSettingsFactory
    from ...configuring.settings import GlobalSettings
    from ...exceptions import LabPublishRefusedError
    from ...labs.publishing import publish as publish_labs

    settings = GlobalSettings.from_yaml(workdir)
    if not skip_checks:
        notebooks = PurePosixPath(
            settings.paths.labs_notebooks_dir.relative_to(settings.paths.git_dir)
        )
        found = [
            finding
            for finding in GlobalSettingsFactory(settings).checks_runner().findings()
            if finding.under(notebooks)
        ]
        if found:
            listed = "\n".join(f"  {f.check}: {f.text}" for f in found)
            msg = (
                f"the content checks report problems in the notebooks:\n{listed}\n"
                "Fix them (each says how) and commit, or pass --skip-checks to "
                "publish them as they are"
            )
            raise LabPublishRefusedError(msg)
    published = publish_labs(
        settings.paths.git_dir,
        settings.paths.labs_notebooks_dir,
        published_dir=settings.paths.labs_published_dir,
        id_metadata_key=settings.labs.id_metadata_key,
        id_pattern=settings.labs.id_pattern,
        remote=settings.labs.publish_remote,
        branch=settings.labs.publish_branch,
        files_remote=settings.labs.published_files_remote,
        files_branch=settings.labs.published_files_branch,
        break_published_links=break_published_links,
        not_secrets=settings.labs.not_secrets,
    )
    print("Published." if published else "Already up to date.")
