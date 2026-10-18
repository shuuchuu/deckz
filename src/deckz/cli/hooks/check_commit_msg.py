from pathlib import Path

from . import app


@app.command(name="check-commit-msg")
def check_commit_msg(message_file: Path, /, *, workdir: Path = Path()) -> None:
    """Mark a commit changing one side of a fr/en pair `Lang-sync: pending`.

    Meant to be called by git's `commit-msg` hook (see `deckz hooks
    install`), MESSAGE_FILE being the path git passes it. When the staged
    changes touch exactly one side of a content/notebook pair and the
    message makes no choice, appends the `Lang-sync: pending` trailer and
    lists the files `deckz i18n stale` will show until they're ported. A
    `fr-only (<why>)`/`en-only (<why>)` trailer in the message is kept; a
    `Lang-sync` line that isn't read as a trailer (misspelled, or
    misplaced) refuses the commit.

    Args:
        message_file: Path of the file holding the draft commit message
        workdir: Path to move into before running the command

    """
    from logging import getLogger

    from ...analyzing.i18n_stale import mark_pending
    from ...configuring.settings import GlobalSettings

    changes = mark_pending(GlobalSettings.from_yaml(workdir), message_file)
    if not changes:
        return
    files = "\n".join(
        f"  {change.changed_path} (not {change.other_path})" for change in changes
    )
    getLogger(__name__).info(
        "these files changed without their other-language version:\n"
        f"{files}\n"
        "The commit is marked Lang-sync: pending, and `deckz i18n stale` lists "
        "them until they're ported. If there's nothing to port (a typo, the "
        "language's own typography): `deckz i18n mark-synced <file> --reason "
        '"<why>"`.'
    )
