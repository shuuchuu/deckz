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

    Raises:
        LabPublishRefusedError: If the labs have commits the upstream branch \
            lacks, or the checks report a problem in a notebook, without \
            --skip-checks.

    """
    from pathlib import PurePosixPath

    from ...checking import export_tree
    from ...components.factory import GlobalSettingsFactory
    from ...configuring.settings import GlobalSettings
    from ...exceptions import LabPublishRefusedError
    from ...labs.publishing import publish as publish_labs
    from ...remotes import publish_remotes, require_remotes
    from ...upstream import source, unpushed

    settings = GlobalSettings.from_yaml(workdir)
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
    published = publish_labs(
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
    print(
        f"Published {found_source.name}'s notebooks."
        if published
        else "Already up to date."
    )


def _tree(git_dir: Path, spec: str) -> str:
    # The object `spec` names (`<rev>:<path>`), "" if it names none.
    import subprocess

    return subprocess.run(
        ["git", "-C", str(git_dir), "rev-parse", "--verify", "--quiet", spec],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
