from pathlib import Path

from . import app, read_payload, report_error


@app.command(name="pre-bash")
def pre_bash(*, workdir: Path = Path()) -> None:
    """Deny a Bash command that would stage everything or discard uncommitted work.

    Wired as Claude Code's PreToolUse hook for Bash by `deckz hooks
    install` (see `deckz.agent_hooks.bash_denial`). A target repo's own
    `templates/hooks.py` can add further denials. Never fails loudly: an
    unreadable payload or an internal error just lets the command through,
    same as finding nothing to deny -- a guard rail for a checkout shared
    with other sessions, not a sandbox.

    Args:
        workdir: Path to move into before resolving settings

    """
    from json import dumps

    try:
        from ...agent_hooks import bash_denial
        from ...configuring.settings import GlobalSettings

        settings = GlobalSettings.from_yaml(workdir)
        reason = bash_denial(settings, read_payload())
    except Exception as error:
        report_error("pre-bash", error)
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
