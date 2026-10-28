from pathlib import Path

from . import app, read_payload


@app.command(name="worktree-create")
def worktree_create(*, workdir: Path = Path()) -> None:
    """Create the worktree Claude Code asks for with `deckz worktree add`.

    Wired as Claude Code's WorktreeCreate hook by `deckz hooks install`
    (see `deckz.agent_checkouts.create_worktree`): `claude --worktree
    <name>`, EnterWorktree with a name and a subagent's worktree isolation
    get a `deckz worktree`, builds included, instead of git's bare one;
    `claude --worktree <name> --resume <session>` gets the existing one back.
    Prints its path, as Claude Code expects; anything else goes to stderr,
    such as what `deckz setup` left missing for every checkout (a tool the
    machine lacks), which doesn't fail the creation.

    Args:
        workdir: Path to move into before resolving settings

    Raises:
        SystemExit: With code 1 when the worktree can't be made or its own
            setup failed, which Claude Code reports as a failed creation.
    """
    from contextlib import redirect_stdout
    from sys import stderr

    from ...agent_checkouts import create_worktree
    from ...configuring.settings import GlobalSettings

    try:
        with redirect_stdout(stderr):
            created = create_worktree(
                GlobalSettings.from_yaml(workdir), read_payload().get("name") or ""
            )
    except Exception as error:
        print(f"deckz hooks worktree-create: {error}", file=stderr)
        raise SystemExit(1) from error
    for item in created.unset:
        print(
            f"deckz hooks worktree-create: warning: {item.name} {item.status.value}, "
            f"in every checkout: {item.detail}",
            file=stderr,
        )
    print(created.path)


@app.command(name="worktree-remove")
def worktree_remove(*, workdir: Path = Path()) -> None:
    """Remove a worktree Claude Code made through `deckz hooks worktree-create`.

    Wired as Claude Code's WorktreeRemove hook by `deckz hooks install`:
    `deckz worktree remove`, which refuses while the worktree holds work
    nothing else has (uncommitted changes, unsynced commits), and hands its
    builds over to the main checkout: what it copied and set aside goes to
    stderr.

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
        removed = remove_worktree(GlobalSettings.from_yaml(workdir), Path(path or ""))
    except Exception as error:
        print(f"deckz hooks worktree-remove: kept {path}: {error}", file=stderr)
        raise SystemExit(1) from error
    renders = removed.renders
    print(
        f"deckz hooks worktree-remove: removed {path}; copied "
        f"{len(renders.copied)} build(s) into the main checkout, set aside "
        f"{len(renders.set_aside)}"
        + (f" ({', '.join(renders.set_aside)})" if renders.set_aside else ""),
        file=stderr,
    )
