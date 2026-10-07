from pathlib import Path

from . import app, read_payload, report_error


@app.command(name="stop")
def stop(*, workdir: Path = Path()) -> None:
    """Flag a content file or lab notebook changed on one language side only.

    Wired as Claude Code's Stop hook by `deckz hooks install` (see
    `deckz.agent_hooks.stop_report`), comparing the working tree against
    the snapshot `deckz hooks session-start` took. Never fails loudly: an
    unreadable payload or an internal error just lets the session stop,
    same as finding nothing to report.

    Args:
        workdir: Path to move into before resolving settings

    """
    from json import dumps

    try:
        from ...agent_hooks import stop_report
        from ...configuring.settings import GlobalSettings

        settings = GlobalSettings.from_yaml(workdir)
        report = stop_report(settings, read_payload())
    except Exception as error:
        report_error("stop", error)
        return
    if report:
        print(dumps({"decision": "block", "reason": report}))
