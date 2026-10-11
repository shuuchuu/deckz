from pathlib import Path

from . import app


@app.command()
def mark_synced(
    paths: list[Path],
    /,
    *,
    reason: str,
    workdir: Path = Path(),
) -> None:
    """Record that changes listed by `deckz i18n stale` need no port after all.

    For a commit that changed one language only without the `Lang-sync:
    fr-only (<why>)` trailer it deserved (a case fix, the language's own
    typography): an empty commit with REASON and a `Lang-synced: <path>`
    trailer per file, after which `deckz i18n stale` counts each pair as in
    sync. Nothing staged goes into this commit, and no hook runs (it changes
    no file).

    Args:
        paths: Files `deckz i18n stale` lists (or their siblings)
        reason: Why nothing needs porting, kept in the commit's message
        workdir: Path to move into before running the command

    """
    from ...analyzing.i18n_stale import mark_synced as mark
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    sha, settled = mark(settings, paths, reason)
    for finding in settled:
        print(f"{finding.path}: in sync with {finding.sibling} as of {sha[:8]}")
