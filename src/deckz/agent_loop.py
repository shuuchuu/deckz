"""Run one prompt in fresh Claude Code sessions, one after another, until done.

A long unattended plan (a night of review blocks, say) done in a single agent
session keeps every block in that session's context: by the tenth block it
carries hundreds of thousands of tokens it no longer needs, which every turn
pays for again. The plan already holds what a session needs to resume (its
progress log), so a fresh session per block costs only the rereading. A
coordinating session that hands each block to a fresh subagent works too (a
subagent can start subagents of its own, as a review skill's block does), but
it still grows with every block's brief and report, and only as long as it
remembers to delegate: a top-level session per block, started from outside,
carries nothing over.

Each session is `claude -p` (headless, one prompt, no one to answer), run in
the repository with the prompt and `PROTOCOL` appended: the session ends its
last message with a `DECKZ-LOOP:` line saying whether to start another. The
loop stops at the first session that says `done` or `stop`, fails, or gives no
such line, and after `max_sessions` in any case. Each session's JSON result is
kept under `<git_dir>/.run/agent-loop/<start time>/`.

A session the account's usage limit stops ends as `limit`, mid-share: its edits
are in the working tree, uncommitted, and only that session knows what they
are. With `wait_on_limit`, the loop sleeps until the limit resets (the time its
message gives, `limit_reset`), then reopens that same session (`claude
--resume`) with `RESUME_PROMPT` rather than starting a fresh one in a working
tree it couldn't make sense of. It waits `MAX_LIMIT_WAIT` at most: a weekly
limit, days away, stops the loop like any failure. A loop that did stop there
is started again with `resume`, the session to reopen first.
"""

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic
from time import sleep as _sleep
from typing import Literal
from zoneinfo import ZoneInfo

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

RESUME_PROMPT = """\
(deckz agent loop) This session was stopped before its end (a usage limit,
which has reset since, or the loop itself). Go on from where you stopped. What
your last steps were waiting for (a subagent, a command) is gone: check what
they left before redoing them. Finish your share, then end your final message
with the DECKZ-LOOP line asked for above.
"""

MAX_LIMIT_WAIT = timedelta(hours=6)
"""The longest wait for a usage limit to reset: a five-hour window's, not a week's."""

LIMIT_POLL = timedelta(minutes=15)
"""How long to wait before trying again when the limit's message gives no time."""

_RESET_MARGIN = timedelta(minutes=1)
_JUST_RESET = timedelta(minutes=10)

_MARKER = re.compile(r"^\s*DECKZ-LOOP:\s*(continue|done|stop)\b[ \t]*(.*)$", re.M)
_LIMIT = re.compile(r"\bhit your\b.{0,40}\blimit\b", re.I)
_RESET = re.compile(
    r"\bresets?\s+(?:at\s+)?"
    r"(?:(?P<month>[a-z]{3,9})\.?\s+(?P<day>\d{1,2}),?\s+(?:at\s+)?)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<half>am|pm)?\b"
    r"(?:\s*\((?P<zone>[^)]+)\))?",
    re.I,
)
_MONTHS = (
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
)  # fmt: skip

Status = Literal["continue", "done", "stop", "limit", "error"]

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class SessionOutcome:
    """How one session of the loop ended.

    Attributes:
        number: Its rank in the loop, from 1.
        status: What its `DECKZ-LOOP:` line said, `limit` when the account's
            usage limit stopped it, or `error` when it failed otherwise or
            gave no such line.
        reason: Why it stopped, or failed (the limit's message); empty
            otherwise.
        result: Its final message, without the `DECKZ-LOOP:` line.
        session_id: Claude Code's session id (`claude --resume <id>`), if any.
        cost_usd: What Claude Code reported it cost, if anything.
        duration_s: Its wall-clock duration.
        log: The file holding its JSON result.
        resets_at: When the limit that stopped it resets, if its message says.
    """

    number: int
    status: Status
    reason: str
    result: str
    session_id: str | None
    cost_usd: float | None
    duration_s: float
    log: Path
    resets_at: datetime | None = None


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


def limit_reset(message: str, now: datetime) -> datetime | None:
    """When the usage limit that `message` reports resets.

    Claude Code words it "You've hit your 5-hour limit · resets 9pm
    (Europe/Paris)", with a date before the time when it isn't today's or
    tomorrow's ("resets Nov 14, 9am").

    Args:
        message: The session's final message.
        now: The current time, with its time zone (the one a message that
            names none is read in).

    Returns:
        The next time the clock shows what the message says: within a day
        when it gives no date, and now when that was minutes ago (the limit
        has just reset). None when the message gives no time that can be
        read.
    """
    match = _RESET.search(message)
    if not match:
        return None
    hour, minute = int(match["hour"]), int(match["minute"] or 0)
    half = (match["half"] or "").lower()
    if half:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if half == "pm" else 0)
    try:
        zone = ZoneInfo(match["zone"].strip()) if match["zone"] else now.tzinfo
        local = now.astimezone(zone)
        reset = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if match["month"]:
            month = _MONTHS.index(match["month"][:3].lower()) + 1
            reset = reset.replace(month=month, day=int(match["day"]))
            if reset < local - _JUST_RESET:
                reset = reset.replace(year=reset.year + 1)
        elif reset < local - _JUST_RESET:
            reset += timedelta(days=1)
    except (ValueError, KeyError, OSError):  # no such time, month or time zone
        return None
    return max(reset, local)


def parse_session(
    number: int,
    completed: "subprocess.CompletedProcess[str]",
    *,
    duration_s: float,
    log: Path,
    now: datetime | None = None,
) -> SessionOutcome:
    """Read one session's `claude -p --output-format json` result.

    Args:
        number: Its rank in the loop.
        completed: The finished `claude` process.
        duration_s: Its wall-clock duration.
        log: The file holding its JSON result.
        now: The current time (`limit_reset`), the system's by default.

    Returns:
        Its outcome: `limit` when the account's usage limit stopped it,
        `error` when claude failed, reported another error, or the final
        message has no `DECKZ-LOOP:` line; the last such line otherwise.
    """

    def outcome(
        status: Status,
        reason: str,
        result: str = "",
        data: dict | None = None,
        resets_at: datetime | None = None,
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
            resets_at=resets_at,
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
        if data.get("api_error") == "usage_limit_reached" or _LIMIT.search(result):
            return outcome(
                "limit",
                result.strip()[-300:],
                result,
                data,
                limit_reset(result, now or datetime.now().astimezone()),
            )
        subtype = data.get("subtype") or f"exit code {completed.returncode}"
        return outcome("error", f"{subtype}: {result.strip()[-300:]}", result, data)
    markers = list(_MARKER.finditer(result))
    if not markers:
        return outcome("error", "the session gave no DECKZ-LOOP line", result, data)
    last = markers[-1]
    status: Status = last[1]  # type: ignore[assignment]
    text = (result[: last.start()] + result[last.end() :]).strip()
    return outcome(status, last[2].strip(), text, data)


def _limit_wait(
    outcome: SessionOutcome, now: datetime, polled: timedelta
) -> timedelta | None:
    """How long to wait before reopening the session a usage limit stopped.

    Args:
        outcome: The `limit` outcome.
        now: The current time.
        polled: How long the loop has waited already without knowing when
            the limit resets.

    Returns:
        Until the reset and a margin, or `LIMIT_POLL` when the reset is
        unknown; None when that goes beyond `MAX_LIMIT_WAIT`.
    """
    if outcome.resets_at is None:
        return LIMIT_POLL if polled + LIMIT_POLL <= MAX_LIMIT_WAIT else None
    wait = max(outcome.resets_at - now, timedelta()) + _RESET_MARGIN
    return wait if wait <= MAX_LIMIT_WAIT else None


def _sleep_until(
    until: datetime, sleep: Callable[[float], None], clock: Callable[[], datetime]
) -> None:
    """Sleep until the clock shows `until`, however long the machine was suspended."""
    while (left := (until - clock()).total_seconds()) > 0:
        sleep(min(left, 60))


def agent_loop(
    prompt: str,
    *,
    git_dir: Path,
    max_sessions: int,
    command: Sequence[str],
    wait_on_limit: bool = False,
    resume: str | None = None,
    on_session: Callable[[SessionOutcome], None] | None = None,
    on_wait: Callable[[SessionOutcome, datetime], None] | None = None,
    runner: Runner | None = None,
    sleep: Callable[[float], None] = _sleep,
    clock: Callable[[], datetime] | None = None,
) -> list[SessionOutcome]:
    """Run `prompt` in one fresh session after another, until one doesn't say continue.

    Args:
        prompt: What every session is asked, `PROTOCOL` appended.
        git_dir: The repository the sessions run in.
        max_sessions: The most sessions to start; reopening one a usage limit
            stopped doesn't count.
        command: The `claude` command line (`claude_command`).
        wait_on_limit: Whether to wait for a usage limit to reset, then
            reopen the session it stopped (`--resume`, `RESUME_PROMPT`),
            instead of stopping there. The wait ends at the time the limit's
            message gives when it is at most `MAX_LIMIT_WAIT` away; when it
            gives none, the session is tried again every `LIMIT_POLL`, for
            `MAX_LIMIT_WAIT` at most. A session that can't be reopened gives
            way to a fresh one.
        resume: The id of a session to reopen first, the same way: the one
            an earlier loop left unfinished.
        on_session: Called with each session's outcome as soon as it ends.
        on_wait: Called before each wait, with the outcome waited on and the
            time the session is reopened.
        runner: `subprocess.run` by default, or a stand-in in tests.
        sleep: `time.sleep` by default, or a stand-in in tests.
        clock: The current time with its time zone; the system's by default.

    Returns:
        Each run's outcome, in order: a reopened session has an outcome per
        run, under the same session id.
    """
    log_dir = git_dir / ".run" / "agent-loop" / datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)
    full_prompt = prompt + PROTOCOL
    (log_dir / "prompt.txt").write_text(full_prompt, encoding="utf8")
    run = runner or subprocess.run
    clock = clock or (lambda: datetime.now().astimezone())
    outcomes: list[SessionOutcome] = []
    started = 0
    polled = timedelta()
    while resume or started < max_sessions:
        number = len(outcomes) + 1
        started += resume is None
        start = monotonic()
        completed = run(
            [*command, "--resume", resume] if resume else list(command),
            input=RESUME_PROMPT if resume else full_prompt,
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
            number, completed, duration_s=monotonic() - start, log=log, now=clock()
        )
        outcomes.append(outcome)
        if on_session:
            on_session(outcome)
        resumed, resume = resume, None
        if outcome.status == "continue":
            polled = timedelta()
            continue
        if resumed and outcome.status == "error" and outcome.session_id is None:
            continue  # claude couldn't reopen it: a fresh session takes the share
        if outcome.status != "limit" or not wait_on_limit:
            break
        wait = _limit_wait(outcome, clock(), polled)
        if wait is None:
            break
        polled = polled + wait if outcome.resets_at is None else timedelta()
        until = clock() + wait
        if on_wait:
            on_wait(outcome, until)
        _sleep_until(until, sleep, clock)
        resume = outcome.session_id
    return outcomes
