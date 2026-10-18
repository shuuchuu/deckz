from pathlib import Path

from . import app


@app.command(name="check-commits")
def check_commits(revisions: str, /, *, workdir: Path = Path()) -> None:
    """Refuse the commits of REVISIONS the commit-msg hook would have refused.

    For CI (see `deckz hooks install --ci`), for a contributor who never
    installed the hooks: each commit changing one side of a fr/en pair
    whose `Lang-sync` line isn't read as a trailer. A commit with no
    `Lang-sync` line at all leaves the pair pending, as the hook would
    have marked it: it's listed, not refused. REVISIONS is a git range
    such as `origin/main..HEAD`.

    Args:
        revisions: The commits to check, as a git revision range
        workdir: Path to move into before running the command

    Raises:
        CommitRefusedError: If a commit's `Lang-sync` line isn't read.
    """
    from logging import getLogger

    from ...analyzing.i18n_stale import one_sided_commits
    from ...configuring.settings import GlobalSettings
    from ...exceptions import CommitRefusedError

    found = one_sided_commits(GlobalSettings.from_yaml(workdir), revisions)
    pending = [commit for commit in found if commit.unread is None]
    if pending:
        getLogger(__name__).info(
            "these commits leave a translation pending (`deckz i18n stale`):\n"
            + "\n".join(f"{commit.sha[:10]} {commit.subject}" for commit in pending)
        )
    unread = [commit for commit in found if commit.unread is not None]
    if not unread:
        return
    lines = [
        f"{commit.sha[:10]} {commit.subject}: {commit.unread}" for commit in unread
    ]
    msg = (
        "these commits have a Lang-sync line that isn't read as a trailer, so "
        "their files count as pending:\n" + "\n".join(lines) + "\nFor each "
        "file with nothing to port, run `deckz i18n mark-synced <file> --reason "
        '"<why>"`; the others leave `deckz i18n stale` once ported.'
    )
    raise CommitRefusedError(msg)
