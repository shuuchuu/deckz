from pathlib import Path

from . import app


@app.command(name="check-commit-msg")
def check_commit_msg(message_file: Path, /, *, workdir: Path = Path()) -> None:
    """Refuse a commit changing one side of a fr/en pair with no `Lang-sync` trailer.

    Meant to be called by git's `commit-msg` hook (see `deckz hooks
    install`), MESSAGE_FILE being the path git passes it. Does nothing if
    the staged changes don't touch exactly one side of any tracked
    content/notebook pair.

    Args:
        message_file: Path of the file holding the draft commit message
        workdir: Path to move into before running the command

    Raises:
        CommitRefusedError: If the staged changes need a trailer that \
            the draft message doesn't carry.

    """
    from ...analyzing.i18n_stale import lang_sync_kind, staged_one_sided_pairs
    from ...configuring.settings import GlobalSettings
    from ...exceptions import CommitRefusedError

    settings = GlobalSettings.from_yaml(workdir)
    one_sided = staged_one_sided_pairs(settings)
    if not one_sided:
        return
    message = message_file.read_text(encoding="utf-8")
    if lang_sync_kind(message) is not None:
        return

    pairs = "\n".join(f"  {fr} / {en}" for fr, en in one_sided)
    msg = (
        "one side of a fr/en pair changed with no Lang-sync trailer:\n"
        f"{pairs}\n"
        "add a trailer to the commit message: Lang-sync: fr-only (<reason>) | "
        "en-only (<reason>) | pending"
    )
    raise CommitRefusedError(msg)
