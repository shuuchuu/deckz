from pathlib import Path

from . import app, read_payload, report_error


@app.command(name="session-start")
def session_start(*, workdir: Path = Path()) -> None:
    """Prune old hook states; tell a session in the main checkout to use a worktree.

    Wired as Claude Code's SessionStart hook by `deckz hooks install` (see
    `deckz.agent_hooks.session_start`): when `deckz.yml` sets
    `worktree.required_for_agents`, a session starting in the main checkout
    is told to work in a worktree of its own. Never fails loudly: an
    internal error just says nothing.

    Args:
        workdir: Path to move into before resolving settings

    """
    from json import dumps

    try:
        from ...agent_hooks import session_start as _session_start
        from ...configuring.settings import GlobalSettings

        settings = GlobalSettings.from_yaml(workdir)
        context = _session_start(settings, read_payload())
    except Exception as error:
        report_error("session-start", error)
        return
    if context:
        print(
            dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": context,
                    }
                }
            )
        )
