from pathlib import Path

from . import app


@app.command(name="check-commits")
def check_commits(revisions: str, /, *, workdir: Path = Path()) -> None:
    """Refuse the commits of REVISIONS the commit-msg hook would have refused.

    For CI (see `deckz hooks install --ci`): each commit changing one side
    of a fr/en pair with no `Lang-sync` trailer, e.g. from a contributor who
    never installed the hooks. REVISIONS is a git range such as
    `origin/main..HEAD`.

    Args:
        revisions: The commits to check, as a git revision range
        workdir: Path to move into before running the command

    Raises:
        CommitRefusedError: If a commit needs a trailer it doesn't carry.
    """
    from ...analyzing.i18n_stale import one_sided_commits
    from ...configuring.settings import GlobalSettings
    from ...exceptions import CommitRefusedError

    found = one_sided_commits(GlobalSettings.from_yaml(workdir), revisions)
    if not found:
        return
    lines = []
    for commit in found:
        lines.append(f"{commit.sha[:10]} {commit.subject}")
        lines += [
            f"  {change.changed_path} (not {change.other_path})"
            for change in commit.changes
        ]
    msg = (
        "these commits change one language of a fr/en pair with no Lang-sync "
        "trailer:\n" + "\n".join(lines) + "\nReword them with a trailer "
        "(Lang-sync: pending, or <side>-only (<why>)), or port the change."
    )
    raise CommitRefusedError(msg)
