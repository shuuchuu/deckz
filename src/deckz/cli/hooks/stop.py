from . import app


@app.command(name="stop", show=False)
def stop() -> None:
    """Do nothing: deckz has no Stop hook any more.

    Kept so that a checkout whose `.claude/settings.json` still names
    `deckz hooks stop` (a worktree made before `deckz hooks install` removed
    it) stops without an error. The pre-commit and commit-msg hooks do what
    it did, on what gets committed.
    """
