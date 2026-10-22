from pathlib import Path

from . import app


@app.command
def land(name: str | None = None, /, *, workdir: Path = Path()) -> None:
    """Put a worktree's commits on the main checkout's branch.

    Rebases the worktree's branch onto the main checkout's, then
    fast-forwards the main checkout to it. Pushing stays a separate step.

    Args:
        name: The worktree's name, as `deckz worktree list` shows it; by
            default, the worktree the command runs in
        workdir: Path to move into before running the command
    """
    from ...configuring.settings import GlobalSettings
    from ...worktrees import land as _land

    branch, count = _land(GlobalSettings.from_yaml(workdir), name)
    print(f"{branch} gained {count} commit(s)")
