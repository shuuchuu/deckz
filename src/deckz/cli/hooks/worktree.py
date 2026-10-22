from pathlib import Path

from . import app, read_payload


@app.command(name="worktree-create")
def worktree_create(*, workdir: Path = Path()) -> None:
    """Create the worktree Claude Code asks for with `deckz worktree add`.

    Wired as Claude Code's WorktreeCreate hook by `deckz hooks install`
    (see `deckz.agent_checkouts.create_worktree`): `claude --worktree
    <name>`, EnterWorktree with a name and a subagent's worktree isolation
    get a `deckz worktree`, builds included, instead of git's bare one.
    Prints its path, as Claude Code expects; anything else goes to stderr.

    Args:
        workdir: Path to move into before resolving settings

    Raises:
        SystemExit: With code 1 when the worktree can't be made, which
            Claude Code reports as a failed creation.
    """
    from contextlib import redirect_stdout
    from sys import stderr

    from ...agent_checkouts import create_worktree
    from ...configuring.settings import GlobalSettings

    try:
        with redirect_stdout(stderr):
            path = create_worktree(
                GlobalSettings.from_yaml(workdir), read_payload().get("name") or ""
            )
    except Exception as error:
        print(f"deckz hooks worktree-create: {error}", file=stderr)
        raise SystemExit(1) from error
    print(path)


@app.command(name="worktree-remove")
def worktree_remove(*, workdir: Path = Path()) -> None:
    """Remove a worktree Claude Code made through `deckz hooks worktree-create`.

    Wired as Claude Code's WorktreeRemove hook by `deckz hooks install`:
    `deckz worktree remove`, which refuses while the worktree holds work
    nothing else has (uncommitted changes, unsynced commits).

    Args:
        workdir: Path to move into before resolving settings

    Raises:
        SystemExit: With code 1 when the worktree is kept.
    """
    from sys import stderr

    from ...agent_checkouts import remove_worktree
    from ...configuring.settings import GlobalSettings

    path = read_payload().get("worktree_path")
    try:
        remove_worktree(GlobalSettings.from_yaml(workdir), Path(path or ""))
    except Exception as error:
        print(f"deckz hooks worktree-remove: kept {path}: {error}", file=stderr)
        raise SystemExit(1) from error
