from pathlib import Path

from . import app


@app.command()
def publish(
    *,
    break_published_links: bool = False,
    replace_unknown: bool = False,
    skip_checks: bool = False,
    workdir: Path = Path(),
) -> None:
    """Replace the labs remote's branch with one commit of the upstream's notebooks.

    The notebooks published are those of the main checkout's upstream branch
    (`origin/main`), fetched first, whichever checkout this runs in: one
    behind it publishes the same, and nothing older goes back in place of
    what's published. A repository with no upstream publishes HEAD's. The
    files committed under `labs/published/` (`paths.labs_published_dir`)
    are published too, at the same paths: in the same commit, or, when
    `labs.published_files_remote` is set, in a commit of their own that
    replaces that remote's branch (e.g. the repository a Codespace opens).

    Refuses to publish if either directory has uncommitted changes or
    commits not pushed to the upstream branch (push them first), a
    notebook has no valid or unique ID (run `deckz labs ids` first) or
    holds what looks like a credential (see the `lab-secrets` check), the
    content checks report a problem in a notebook (deferred ones included:
    `lab-pairs`, `lab-format`, `lab-outputs`..., which let a commit through
    but not the notebooks going public; run on the upstream's version when
    it differs from this checkout's), doing so would drop an
    already-published notebook's name, or replace a published version the
    upstream's history doesn't hold (published from commits never pushed).
    A missing remote, one that can't be reached or refuses the push fails
    with git's message and the fix (`setup.remotes` gives `deckz setup` the
    remotes to add).

    Args:
        break_published_links: Allow removing an already-published
            notebook's link
        replace_unknown: Allow replacing a published version the upstream's
            history doesn't hold
        skip_checks: Don't run the content checks: publish whatever they
            would report, but a credential, still refused
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...publishing import publish_labs

    published, found_source = publish_labs(
        GlobalSettings.from_yaml(workdir),
        break_published_links=break_published_links,
        replace_unknown=replace_unknown,
        skip_checks=skip_checks,
    )
    print(
        f"Published {found_source.name}'s notebooks."
        if published
        else "Already up to date."
    )
