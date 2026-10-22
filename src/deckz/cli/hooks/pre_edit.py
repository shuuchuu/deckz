from pathlib import Path

from . import app, read_payload, report_error


@app.command(name="pre-edit")
def pre_edit(*, workdir: Path = Path()) -> None:
    """Deny an edit of the main checkout when agents work in worktrees only.

    Wired as Claude Code's PreToolUse hook for the edit tools by `deckz
    hooks install` (see `deckz.agent_checkouts.edit_denial`); does nothing
    unless `deckz.yml` sets `worktree.required_for_agents`. Never fails
    loudly: an unreadable payload or an internal error just lets the edit
    through.

    Args:
        workdir: Path to move into before resolving settings

    """
    from json import dumps

    try:
        from ...agent_checkouts import edit_denial
        from ...configuring.settings import GlobalSettings

        settings = GlobalSettings.from_yaml(workdir)
        reason = edit_denial(settings, read_payload())
    except Exception as error:
        report_error("pre-edit", error)
        return
    if reason:
        print(
            dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
            )
        )
