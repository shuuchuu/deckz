"""Run one prompt in fresh Claude Code sessions, one after another, until done.

A long unattended plan (a night of review blocks, say) done in a single agent
session keeps every block in that session's context: by the tenth block it
carries hundreds of thousands of tokens it no longer needs, which every turn
pays for again. The plan already holds what a session needs to resume (its
progress log), so a fresh session per block costs only the rereading. A
coordinating session can't get that by handing each block to a subagent when
the block itself runs subagents (a review skill does), since a subagent can't
start its own: hence one top-level session per block, started from outside.

Each session is `claude -p` (headless, one prompt, no one to answer), run in
the repository with the prompt and `PROTOCOL` appended: the session ends its
last message with a `DECKZ-LOOP:` line saying whether to start another. The
loop stops at the first session that says `done` or `stop`, fails, or gives no
such line, and after `max_sessions` in any case. Each session's JSON result is
kept under `<git_dir>/.run/agent-loop/<start time>/`.
"""

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Literal

PROTOCOL = """

---

(deckz agent loop) This prompt runs again in a fresh session once this one
ends, until a session reports that nothing is left. Do the share of the work
the prompt gives one session, record it where the work is tracked, then stop.
End your final message with exactly one of these lines:

DECKZ-LOOP: continue
DECKZ-LOOP: done
DECKZ-LOOP: stop <why>

`continue`: your share is done and recorded, and more is left. `done`: nothing
is left. `stop`: you can't go on, or the next session couldn't either,
without the user (name why).
"""

_MARKER = re.compile(r"^\s*DECKZ-LOOP:\s*(continue|done|stop)\b[ \t]*(.*)$", re.M)

Status = Literal["continue", "done", "stop", "error"]

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class SessionOutcome:
    """How one session of the loop ended.

    Attributes:
        number: Its rank in the loop, from 1.
        status: What its `DECKZ-LOOP:` line said, or `error` when it failed
            or gave no such line.
        reason: Why it stopped, or failed; empty otherwise.
        result: Its final message, without the `DECKZ-LOOP:` line.
        session_id: Claude Code's session id (`claude --resume <id>`), if any.
        cost_usd: What Claude Code reported it cost, if anything.
        duration_s: Its wall-clock duration.
        log: The file holding its JSON result.
    """

    number: int
    status: Status
    reason: str
    result: str
    session_id: str | None
    cost_usd: float | None
    duration_s: float
    log: Path


def claude_command(
    *, permission_mode: str = "auto", model: str | None = None
) -> list[str]:
    """The `claude` command line of one session.

    Returns:
        Its arguments; the prompt goes on stdin, not on the command line.
    """
    command = ["claude", "-p", "--output-format", "json"]
    command += ["--permission-mode", permission_mode]
    if model:
        command += ["--model", model]
    return command


def parse_session(
    number: int,
    completed: "subprocess.CompletedProcess[str]",
    *,
    duration_s: float,
    log: Path,
) -> SessionOutcome:
    """Read one session's `claude -p --output-format json` result.

    Returns:
        Its outcome: `error` when claude failed, reported an error, or the
        final message has no `DECKZ-LOOP:` line; the last such line otherwise.
    """

    def outcome(
        status: Status, reason: str, result: str = "", data: dict | None = None
    ) -> SessionOutcome:
        data = data or {}
        cost = data.get("total_cost_usd")
        return SessionOutcome(
            number=number,
            status=status,
            reason=reason,
            result=result,
            session_id=data.get("session_id"),
            cost_usd=float(cost) if isinstance(cost, int | float) else None,
            duration_s=duration_s,
            log=log,
        )

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        error = (completed.stderr or completed.stdout).strip().splitlines()
        return outcome(
            "error",
            f"claude exited with code {completed.returncode}: "
            + (error[-1] if error else "no output"),
        )
    if not isinstance(data, dict):
        return outcome("error", "claude printed no JSON object")
    result = str(data.get("result") or "")
    if data.get("is_error") or completed.returncode:
        subtype = data.get("subtype") or f"exit code {completed.returncode}"
        return outcome("error", f"{subtype}: {result.strip()[-300:]}", result, data)
    markers = list(_MARKER.finditer(result))
    if not markers:
        return outcome("error", "the session gave no DECKZ-LOOP line", result, data)
    last = markers[-1]
    status: Status = last[1]  # type: ignore[assignment]
    text = (result[: last.start()] + result[last.end() :]).strip()
    return outcome(status, last[2].strip(), text, data)


def agent_loop(
    prompt: str,
    *,
    git_dir: Path,
    max_sessions: int,
    command: Sequence[str],
    on_session: Callable[[SessionOutcome], None] | None = None,
    runner: Runner | None = None,
) -> list[SessionOutcome]:
    """Run `prompt` in one fresh session after another, until one doesn't say continue.

    Args:
        prompt: What every session is asked, `PROTOCOL` appended.
        git_dir: The repository the sessions run in.
        max_sessions: The most sessions to start.
        command: The `claude` command line (`claude_command`).
        on_session: Called with each session's outcome as soon as it ends.
        runner: `subprocess.run` by default, or a stand-in in tests.

    Returns:
        Each session's outcome, in order.
    """
    log_dir = git_dir / ".run" / "agent-loop" / datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)
    full_prompt = prompt + PROTOCOL
    (log_dir / "prompt.txt").write_text(full_prompt, encoding="utf8")
    run = runner or subprocess.run
    outcomes: list[SessionOutcome] = []
    for number in range(1, max_sessions + 1):
        start = monotonic()
        completed = run(
            list(command),
            input=full_prompt,
            capture_output=True,
            text=True,
            cwd=git_dir,
            check=False,
        )
        log = log_dir / f"session-{number:02}.json"
        log.write_text(completed.stdout or "", encoding="utf8")
        if completed.stderr:
            log.with_suffix(".err").write_text(completed.stderr, encoding="utf8")
        outcome = parse_session(
            number, completed, duration_s=monotonic() - start, log=log
        )
        outcomes.append(outcome)
        if on_session:
            on_session(outcome)
        if outcome.status != "continue":
            break
    return outcomes
