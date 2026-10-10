from pathlib import Path

from . import app


@app.command
def remove(name: str, /, *, force: bool = False, workdir: Path = Path()) -> None:
    """Remove a worktree, and its branch once nothing would be lost.

    Refuses while the worktree has uncommitted changes, or commits that no
    other branch, local or remote, has.

    Args:
        name: The worktree's name, as `deckz worktree list` shows it
        force: Remove it anyway: its uncommitted changes are lost, its
            unsynced commits stay on its branch
        workdir: Path to move into before running the command
    """
    from ...configuring.settings import GlobalSettings
    from ...worktrees import BRANCH_PREFIX
    from ...worktrees import remove as _remove

    kept = _remove(GlobalSettings.from_yaml(workdir), name, force=force)
    print(f"removed the worktree {name}")
    if kept:
        print(f"kept the branch {BRANCH_PREFIX}{name}: it has unsynced commits")
