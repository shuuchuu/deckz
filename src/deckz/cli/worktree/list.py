from pathlib import Path

from . import app


@app.command(name="list")
def list_(*, json: bool = False, workdir: Path = Path()) -> None:
    """List the worktrees: path, uncommitted changes, unsynced commits.

    Args:
        json: Print a JSON list instead
        workdir: Path to move into before running the command
    """
    from dataclasses import asdict

    from ...configuring.settings import GlobalSettings
    from ...worktrees import worktrees

    found = worktrees(GlobalSettings.from_yaml(workdir))
    if json:
        from .._presentation import print_json

        print_json([asdict(w) for w in found])
        return
    if not found:
        print("no worktree (`deckz worktree add NAME` creates one)")
    for worktree in found:
        print(
            f"{worktree.name}  {worktree.path}  "
            f"{len(worktree.changes)} uncommitted change(s), "
            f"{worktree.unsynced} unsynced commit(s)"
        )
