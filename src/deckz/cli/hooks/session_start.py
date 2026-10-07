from pathlib import Path

from . import app, read_payload, report_error


@app.command(name="session-start")
def session_start(*, workdir: Path = Path()) -> None:
    """Snapshot the repo's fr/en content and notebook pairs for this session.

    Wired as Claude Code's SessionStart hook by `deckz hooks install` (see
    `deckz.agent_hooks.session_start`): `deckz hooks stop` diffs against
    this snapshot to flag a pair changed on one language side only. Never
    fails loudly: an internal error just skips the snapshot.

    Args:
        workdir: Path to move into before resolving settings

    """
    try:
        from ...agent_hooks import session_start as _session_start
        from ...configuring.settings import GlobalSettings

        settings = GlobalSettings.from_yaml(workdir)
        _session_start(settings, read_payload())
    except Exception as error:
        report_error("session-start", error)
        return
