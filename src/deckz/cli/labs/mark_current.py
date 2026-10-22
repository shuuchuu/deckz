from pathlib import Path

from . import app


@app.command()
def mark_current(
    notebooks: list[Path],
    /,
    *,
    reason: str,
    workdir: Path = Path(),
) -> None:
    """Record that demos listed by `deckz labs stale` need no rerun after all.

    For code changes that change no output that matters (a comment, a
    download line, a sweeping rename): an empty commit with REASON and a
    `Lab-outputs-current: <path>` trailer per notebook, after which `deckz
    labs stale` takes their outputs as current. A commit making such a
    change can carry the trailers itself. Nothing staged goes into this
    commit, and no hook runs (it changes no file).

    Args:
        notebooks: Demos `deckz labs stale` lists
        reason: Why their outputs need no rerun, kept in the commit's message
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...labs.stale_outputs import mark_current as mark

    settings = GlobalSettings.from_yaml(workdir)
    sha, settled = mark(settings, notebooks, reason)
    for demo in settled:
        print(f"{demo.path}: outputs current as of {sha[:8]}")
