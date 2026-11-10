from pathlib import Path

from . import app


@app.command
def loop(
    prompt: str,
    *,
    max_sessions: int = 20,
    model: str | None = None,
    permission_mode: str = "auto",
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Run PROMPT in one fresh Claude Code session after another, until done.

    For a plan done block by block without anyone watching (a night of
    reviews): each session does one share of the work, records it where the
    plan tracks progress, and ends with a `DECKZ-LOOP: continue|done|stop`
    line, which the instructions appended to PROMPT ask for. A fresh session
    rereads the plan instead of carrying every past block in its context.

    Each session is `claude -p --output-format json`, run at the repository's
    root, prompt on stdin. The loop stops at the first session that says
    `done` or `stop`, fails (a usage limit, say) or gives no such line, and
    after --max-sessions. Each session's JSON result is kept under
    `.run/agent-loop/<start time>/`; `claude --resume <session id>` reopens
    one. Exits 1 unless the last session said `done` or `continue`.

    Args:
        prompt: What every session is asked, e.g. "Reprends
            docs/plans/<plan>.md, file C, un seul bloc"
        max_sessions: The most sessions to start
        model: The sessions' model (`claude --model`); Claude Code's default
            otherwise
        permission_mode: The sessions' permission mode (`claude
            --permission-mode`): `auto` lets them work with no one to
            approve, within Claude Code's safeguards and the repository's
            hooks
        json: Print the sessions' outcomes as a JSON list once done
        workdir: Path to move into before running the command

    Raises:
        SystemExit: With code 1 when the last session said `stop` or failed.
    """
    import logging
    from dataclasses import asdict

    from ...agent_loop import SessionOutcome, agent_loop, claude_command
    from ...utils import get_git_dir

    logger = logging.getLogger(__name__)
    command = claude_command(permission_mode=permission_mode, model=model)
    logger.info("each session runs: %s", " ".join(command))

    def report(outcome: SessionOutcome) -> None:
        cost = f", ${outcome.cost_usd:.2f}" if outcome.cost_usd is not None else ""
        logger.info(
            "session %d: %s%s (%.0f min%s, %s)",
            outcome.number,
            outcome.status,
            f": {outcome.reason}" if outcome.reason else "",
            outcome.duration_s / 60,
            cost,
            outcome.session_id or outcome.log,
        )

    outcomes = agent_loop(
        prompt,
        git_dir=get_git_dir(workdir.resolve()),
        max_sessions=max_sessions,
        command=command,
        on_session=report,
    )
    if json:
        from .._presentation import print_json

        print_json([asdict(o) for o in outcomes])
    else:
        last = outcomes[-1]
        if last.result:
            print(last.result)
        if last.status == "continue":
            print(f"stopped after --max-sessions {max_sessions}: more is left")
        else:
            reason = f": {last.reason}" if last.reason else ""
            print(f"last session: {last.status}{reason}")
        print(f"logs: {last.log.parent}")
    if outcomes[-1].status not in ("done", "continue"):
        raise SystemExit(1)
