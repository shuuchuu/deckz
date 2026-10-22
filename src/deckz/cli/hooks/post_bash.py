from pathlib import Path

from . import app, read_payload, report_error


@app.command(name="post-bash")
def post_bash(*, workdir: Path = Path()) -> None:
    """Report what a Bash command changed in the main checkout.

    Wired as Claude Code's PostToolUse and PostToolUseFailure hook for Bash
    by `deckz hooks install` (see `deckz.agent_hooks.post_bash_report`):
    when `deckz.yml` sets `worktree.required_for_agents`, `deckz hooks
    pre-bash` takes a snapshot of the main checkout before a command that
    may change it, and this compares. Never fails loudly: an internal error
    just reports nothing.

    Args:
        workdir: Path to move into before resolving settings

    """
    from json import dumps

    try:
        from ...agent_hooks import post_bash_report
        from ...configuring.settings import GlobalSettings

        payload = read_payload()
        report = post_bash_report(GlobalSettings.from_yaml(workdir), payload)
    except Exception as error:
        report_error("post-bash", error)
        return
    if not report:
        return
    event = payload.get("hook_event_name") or "PostToolUse"
    if event == "PostToolUse":
        print(dumps({"decision": "block", "reason": report}))
    else:
        output = {"hookEventName": event, "additionalContext": report}
        print(dumps({"hookSpecificOutput": output}))
