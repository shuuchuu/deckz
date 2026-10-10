from pathlib import Path

from . import app


@app.command
def add(name: str, /, *, base: str | None = None, workdir: Path = Path()) -> None:
    """Create a worktree next to the main checkout, ready to build.

    Creates `../<repo>--NAME` on a new branch `ws/NAME`, copies the main
    checkout's builds (`deckz.yml`'s `worktree.seed`: what a fresh checkout
    would otherwise rebuild, videos included), symlinks what checkouts share
    (`worktree.link`, e.g. `.env`), then reports `deckz setup --check` there.

    Args:
        name: The worktree's name (letters, digits, - and _)
        base: Revision to start from (default: the main checkout's HEAD)
        workdir: Path to move into before running the command

    Raises:
        SystemExit: With code 1 when `deckz setup --check` finds something
            missing in the new worktree.
    """
    from ...configuring.settings import GlobalSettings
    from ...setting_up import incomplete, setup
    from ...worktrees import add as _add
    from .._presentation import print_setup

    added = _add(GlobalSettings.from_yaml(workdir), name, base)
    print(f"created {added.path} on {added.branch}, from {added.base[:12]}")
    print(f"copied {added.copied} built file(s) from the main checkout")
    for entry in added.linked:
        print(f"linked {entry}")
    for reason in added.not_linked:
        print(f"not linked {reason}")
    items = setup(GlobalSettings.from_yaml(added.path), check=True)
    print_setup(items)
    if incomplete(items):
        raise SystemExit(1)
