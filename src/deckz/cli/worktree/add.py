from pathlib import Path

from . import app


@app.command
def add(name: str, /, *, base: str | None = None, workdir: Path = Path()) -> None:
    """Create a worktree next to the main checkout, ready to build.

    Creates `../<repo>--NAME` on a new branch `ws/NAME`, copies the main
    checkout's builds (`deckz.yml`'s `worktree.seed`: what a fresh checkout
    would otherwise rebuild, videos included), then runs `deckz setup` there
    (e.g. its own Python environment, in a second from uv's cache).

    Args:
        name: The worktree's name (letters, digits, - and _)
        base: Revision to start from (default: the main checkout's HEAD)
        workdir: Path to move into before running the command

    Raises:
        SystemExit: With code 1 when `deckz setup` leaves something missing
            or failed in the new worktree.
    """
    from ...configuring.settings import GlobalSettings
    from ...setting_up import incomplete, setup
    from ...worktrees import add as _add
    from .._presentation import RichProgress, print_setup

    added = _add(GlobalSettings.from_yaml(workdir), name, base)
    print(f"created {added.path} on {added.branch}, from {added.base[:12]}")
    print(f"copied {added.copied} built file(s) from the main checkout")
    items = setup(GlobalSettings.from_yaml(added.path), progress=RichProgress())
    print_setup(items)
    if incomplete(items):
        raise SystemExit(1)
