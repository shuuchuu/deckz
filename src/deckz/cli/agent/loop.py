from pathlib import Path

from . import app


@app.command
def loop(
    prompt: str,
    *,
    max_sessions: int = 20,
    model: str | None = None,
    permission_mode: str = "auto",
    wait_on_limit: bool = False,
    resume: str | None = None,
    steps: bool = True,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Run PROMPT in one fresh Claude Code session after another, until done.

    For a plan done block by block without anyone watching (a night of
    reviews): each session does one share of the work, records it where the
    plan tracks progress, and ends with a `DECKZ-LOOP: continue|done|stop`
    line, which the instructions appended to PROMPT ask for. A fresh session
    rereads the plan instead of carrying every past block in its context.

    Each session is `claude -p --output-format stream-json`, run at the
    repository's root, prompt on stdin. What it says and the tools it calls
    are logged as it goes (--no-steps: only how each session ended), and each
    session's end says how much of the account's five-hour and seven-day
    usage windows is spent. The loop stops at the first session that says
    `done` or `stop`, fails (a usage limit, say) or gives no such line, and
    after --max-sessions. Each session's JSON result is kept under
    `.run/agent-loop/<start time>/`; `claude --resume <session id>` reopens
    one. Exits 1 unless the last session said `done` or `continue`.

    A usage limit stops a session in the middle of its share, edits
    uncommitted. With --wait-on-limit, the loop then sleeps until the limit
    resets (the time its message gives, 6 hours away at most: not a weekly
    limit) and reopens that session, which goes on from where it stopped.
    A loop that stopped at a limit is started again with --resume and the id
    of the session it cut (the loop's log gives it).

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
        wait_on_limit: Wait for a usage limit to reset, then reopen the
            session it stopped, instead of stopping the loop
        resume: The id of a session to reopen first (one an earlier loop
            left unfinished), before any fresh one
        steps: Log what each session says and the tools it calls, as it
            goes
        json: Print the sessions' outcomes as a JSON list once done
        workdir: Path to move into before running the command

    Raises:
        SystemExit: With code 1 when the last session said `stop` or failed.
    """
    import logging
    from dataclasses import asdict
    from datetime import datetime

    from ...agent_loop import (
        SessionOutcome,
        agent_loop,
        claude_command,
        describe_event,
    )
    from ...utils import get_git_dir

    logger = logging.getLogger(__name__)
    command = claude_command(permission_mode=permission_mode, model=model)
    logger.info("each session runs: %s", " ".join(command))

    def waiting(outcome: SessionOutcome, until: datetime) -> None:
        logger.info(
            "usage limit: waiting until %s, then reopening session %s",
            until.astimezone().strftime("%H:%M"),
            outcome.session_id or "(a fresh one)",
        )

    def show(event: dict) -> None:
        for line in describe_event(event):
            logger.info("%s", line)

    def report(outcome: SessionOutcome) -> None:
        cost = f", ${outcome.cost_usd:.2f}" if outcome.cost_usd is not None else ""
        used = [
            f"{label} {share:.0%}"
            for label, share in (
                ("5-hour window", outcome.window_used),
                ("week", outcome.week_used),
            )
            if share is not None
        ]
        logger.info(
            "session %d: %s%s (%.0f min%s, %s)%s",
            outcome.number,
            outcome.status,
            f": {outcome.reason}" if outcome.reason else "",
            outcome.duration_s / 60,
            cost,
            outcome.session_id or outcome.log,
            f"; usage: {', '.join(used)}" if used else "",
        )

    outcomes = agent_loop(
        prompt,
        git_dir=get_git_dir(workdir.resolve()),
        max_sessions=max_sessions,
        command=command,
        wait_on_limit=wait_on_limit,
        resume=resume,
        on_session=report,
        on_wait=waiting,
        on_event=show if steps else None,
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
            if last.status == "limit":
                print(
                    "not waited for: its reset is too far or unknown"
                    if wait_on_limit
                    else "--wait-on-limit waits for the reset, then reopens the"
                    f" session; later: --resume {last.session_id}"
                )
        print(f"logs: {last.log.parent}")
    if outcomes[-1].status not in ("done", "continue"):
        raise SystemExit(1)
