from pathlib import Path

from . import app, read_payload, report_error


@app.command(name="post-edit")
def post_edit(*, workdir: Path = Path()) -> None:
    """Record an edited file; convert a content file and run the checks on it.

    Wired as Claude Code's PostToolUse hook for the edit tools by `deckz
    hooks install` (see `deckz.agent_hooks.post_edit_report`). Checks
    nothing for a file that isn't a content file, or that no longer
    exists. Never fails loudly: an unreadable payload or an internal error
    just lets the edit stand, same as finding nothing to report.

    Args:
        workdir: Path to move into before resolving settings

    """
    from json import dumps

    try:
        from ...agent_hooks import post_edit_report
        from ...configuring.settings import GlobalSettings

        settings = GlobalSettings.from_yaml(workdir)
        report = post_edit_report(settings, read_payload())
    except Exception as error:
        report_error("post-edit", error)
        return
    if report:
        print(dumps({"decision": "block", "reason": report}))
