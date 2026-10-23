from pathlib import Path

from . import app


@app.command
def remove(name: str, /, *, force: bool = False, workdir: Path = Path()) -> None:
    """Remove a worktree, and its branch once nothing would be lost.

    Refuses while the worktree has uncommitted changes, or commits that no
    other branch, local or remote, has. Its builds (`deckz.yml`'s
    `worktree.seed`: figures, videos) go to the main checkout first: those
    it lacks are copied there; those it holds built from other sources are
    set aside in the git directory, where its builds find them once its
    sources match (a pull), for 30 days.

    Args:
        name: The worktree's name, as `deckz worktree list` shows it
        force: Remove it anyway: its uncommitted changes are lost, its
            unsynced commits stay on its branch
        workdir: Path to move into before running the command
    """
    from ...configuring.settings import GlobalSettings
    from ...worktrees import BRANCH_PREFIX
    from ...worktrees import remove as _remove

    removed = _remove(GlobalSettings.from_yaml(workdir), name, force=force)
    print(f"removed the worktree {name}")
    renders = removed.renders
    if renders.copied:
        print(f"copied {len(renders.copied)} build(s) into the main checkout")
    if renders.set_aside:
        print(
            f"set aside {len(renders.set_aside)} build(s) the main checkout holds "
            "built from other sources (until it adopts them, 30 days at most):"
        )
        for path in renders.set_aside:
            print(f"    {path}")
    if removed.kept_branch:
        print(f"kept the branch {BRANCH_PREFIX}{name}: it has unsynced commits")
