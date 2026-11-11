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

A session prints its events as it goes (`--output-format stream-json`), which
`run_session` reads: what the session says and the tools it calls
(`describe_event`, for whoever watches the loop), how much of the account's
usage windows is spent (kept with the result), and the result itself, the
stream's last `result` event. A session prints one such event per turn, and a
turn can say nothing: the notice that a subagent has finished comes after its
report, and a session that had ended on that report has nothing to add. Such
an event keeps the message of the one before, the session's last words. So
does a turn that comes after the session's `DECKZ-LOOP:` line and gives none:
a wakeup the session had scheduled as a fallback while its subagents ran
(ScheduleWakeup) fires after its final message, and its answer ("nothing
left") must not erase the line. Such a pending wakeup also keeps a headless
session open until it fires, up to an hour later, at the price of a turn on a
context no longer cached: a session that has given its line and stays open
with nothing happening is ended after `SESSION_END_GRACE`, and `PROTOCOL`
asks sessions to leave none.

A session the account's usage limit stops ends as `limit`, mid-share: its edits
are in the working tree, uncommitted, and only that session knows what they
are. With `wait_on_limit`, the loop sleeps until the limit resets (the time its
message gives, `limit_reset`), then reopens that same session (`claude
--resume`) with `RESUME_PROMPT` rather than starting a fresh one in a working
tree it couldn't make sense of. It waits `MAX_LIMIT_WAIT` at most: a weekly
limit, days away, stops the loop like any failure. A loop that did stop there
is started again with `resume`, the session to reopen first.

A session that hands work to subagents ends its turns while they run, and each
of their reports starts it again. Headless, Claude Code waits ten minutes for
them after a turn, then stops them and ends the session on that turn's message
("J'attends les deux rédacteurs"), which has no `DECKZ-LOOP:` line: a subagent
that writes a chapter or runs a notebook takes longer. So a session runs with
that wait set to `BACKGROUND_WAIT` (`session_environment`), and one Claude
Code still ends that way is `cut`: the loop reopens it at once, the same way,
but once only, since what outlasted `BACKGROUND_WAIT` is more likely stuck
than slow.

Nobody can tell a running loop anything: its sessions read no one. So a loop
holds a lock in its log directory while it runs (`running_loops`), and
`request_stop` leaves a `stop` file there, which the loop looks for before it
starts a fresh session: the session at work ends its share first (reopened,
if it is cut), and nothing is left half done. A loop waiting for a usage
limit ends at once instead, without reopening the session the limit cut:
`resume` reopens it later.
"""

import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread, Timer
from time import monotonic
from time import sleep as _sleep
from typing import Literal
from zoneinfo import ZoneInfo

from .exceptions import DeckzError
from .utils import file_lock

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

Leave nothing pending behind that final message: no subagent or background
command still running, and no scheduled wakeup (ScheduleWakeup). The reports
of your subagents reach you without one, and a pending wakeup keeps this
session open after its end, until it fires.
"""

RESUME_PROMPT = """\
(deckz agent loop) This session was stopped before its end: by a usage limit,
which has reset since, by Claude Code, which stopped the background tasks it
had waited on for too long, or by the loop itself. Go on from where you
stopped. What your last steps were waiting for (a subagent, a command) is
gone: check what they left before redoing them. Finish your share, then end
your final message with the DECKZ-LOOP line asked for above.
"""

MAX_LIMIT_WAIT = timedelta(hours=6)
"""The longest wait for a usage limit to reset: a five-hour window's, not a week's."""

LIMIT_POLL = timedelta(minutes=15)
"""How long to wait before trying again when the limit's message gives no time."""

BACKGROUND_WAIT = timedelta(hours=2)
"""How long a session waits, after a turn, for its subagents and background commands.

Claude Code's own default for a headless session is ten minutes.
"""

SESSION_END_GRACE = timedelta(minutes=1)
"""How long a session that gave its `DECKZ-LOOP:` line may stay open, nothing
happening, before the loop ends it."""

BACKGROUND_WAIT_VARIABLE = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"
"""Claude Code's environment variable for that wait, in milliseconds (0: no end)."""

_RESET_MARGIN = timedelta(minutes=1)
_JUST_RESET = timedelta(minutes=10)

_MARKER = re.compile(r"^\s*DECKZ-LOOP:\s*(continue|done|stop)\b[ \t]*(.*)$", re.M)
_LIMIT = re.compile(r"\bhit your\b.{0,40}\blimit\b", re.I)
_CUT = re.compile(r"Background tasks still running[^\n]*?stopping them", re.I)
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

Status = Literal["continue", "done", "stop", "limit", "cut", "error"]

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class SessionOutcome:
    """How one session of the loop ended.

    Attributes:
        number: Its rank in the loop, from 1.
        status: What its `DECKZ-LOOP:` line said, `limit` when the account's
            usage limit stopped it, `cut` when it gave no such line because
            Claude Code stopped the background tasks it was waiting for, or
            `error` when it failed otherwise or gave no such line.
        reason: Why it stopped, or failed (the limit's message, what Claude
            Code said of the tasks it stopped); empty otherwise.
        result: Its final message, without the `DECKZ-LOOP:` line.
        session_id: Claude Code's session id (`claude --resume <id>`), if any.
        cost_usd: What Claude Code reported it cost, if anything.
        duration_s: Its wall-clock duration.
        log: The file holding its JSON result.
        resets_at: When the limit that stopped it resets, if its message or
            its events say.
        window_used: The share of the five-hour usage window spent when it
            ended, from 0 to 1, if its events say.
        week_used: The same for the seven-day window.
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
    window_used: float | None = None
    week_used: float | None = None


def claude_command(
    *, permission_mode: str = "auto", model: str | None = None
) -> list[str]:
    """The `claude` command line of one session.

    Returns:
        Its arguments; the prompt goes on stdin, not on the command line.
    """
    command = ["claude", "-p", "--output-format", "stream-json", "--verbose"]
    command += ["--permission-mode", permission_mode]
    if model:
        command += ["--model", model]
    return command


_LOOP_EVENT = "deckz_loop"  # an event of the loop's own, among the session's

_TOOL_DETAILS = ("description", "file_path", "skill", "command", "pattern", "query")


def describe_event(event: dict) -> list[str]:
    """What an event of a session's stream shows of what the session is doing.

    Args:
        event: One line of `claude -p --output-format stream-json`.

    Returns:
        What the session says, and one line per tool it calls ("→ Bash: Run
        the checks"); what the loop itself did to the session (`run_session`
        ending it); nothing for its subagents' events, tool results, thinking
        and the rest.
    """
    if event.get("type") == _LOOP_EVENT:
        return [str(event.get("text") or "")]
    if event.get("type") != "assistant" or event.get("parent_tool_use_id"):
        return []
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    lines: list[str] = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = str(block.get("text") or "").strip()
            if text:
                lines.append(text)
        elif block.get("type") == "tool_use":
            tool_input = block.get("input")
            tool_input = tool_input if isinstance(tool_input, dict) else {}
            name = str(block.get("name") or "?")
            if tool_input.get("model"):
                name += f" [{tool_input['model']}]"
            detail = next(
                (str(tool_input[k]) for k in _TOOL_DETAILS if tool_input.get(k)), ""
            )
            detail = " ".join(detail.split())
            if len(detail) > 120:
                detail = detail[:119] + "…"
            lines.append(f"→ {name}: {detail}" if detail else f"→ {name}")
    return lines


def session_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment of one session.

    Args:
        environ: The environment to start from, the loop's own by default.

    Returns:
        It, with `BACKGROUND_WAIT_VARIABLE` set to `BACKGROUND_WAIT` unless it
        sets that variable already.
    """
    env = dict(os.environ if environ is None else environ)
    wait_ms = int(BACKGROUND_WAIT.total_seconds() * 1000)
    env.setdefault(BACKGROUND_WAIT_VARIABLE, str(wait_ms))
    return env


def run_session(
    args: Sequence[str],
    *,
    prompt: str,
    cwd: Path,
    on_event: Callable[[dict], None] | None = None,
    end_grace: timedelta = SESSION_END_GRACE,
) -> "subprocess.CompletedProcess[str]":
    """Run one `claude` session, reading its stream of events as it goes.

    It runs in `session_environment`: with the time to wait for its subagents.
    A session that has given its `DECKZ-LOOP:` line and stays open, nothing
    happening, is ended: only something pending keeps it (a scheduled
    wakeup), which it no longer needs.

    Args:
        args: The `claude` command line (`claude_command`).
        prompt: The prompt, given on stdin.
        cwd: The directory the session runs in.
        on_event: Called with each event as soon as the session prints it,
            and with one of the loop's own when it ends the session.
        end_grace: How long the session may stay open that way.

    Returns:
        The finished process, its exit code 0 when the loop ended it. Its
        stdout is the session's result, as one JSON object: the stream's last
        `result` event (`_with_last_message` says with which message), with
        the last usage figures the stream gave under `rate_limit_info`, and
        `ended_by_loop` when the loop ended it; or everything the process
        printed when it gave no such event (it failed before starting).
    """
    result: dict | None = None
    limits: object = None
    other: list[str] = []
    errors: list[str] = []
    with subprocess.Popen(
        list(args),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf8",
        errors="replace",
        cwd=cwd,
        env=session_environment(),
    ) as process:
        assert process.stdin and process.stdout and process.stderr
        stderr = process.stderr
        drain = Thread(target=lambda: errors.append(stderr.read()), daemon=True)
        drain.start()
        try:
            process.stdin.write(prompt)
            process.stdin.close()
        except OSError:  # it exited without reading its prompt
            pass
        idle = _IdleEnd(process, end_grace)
        for line in process.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = None
            if not isinstance(event, dict) or "type" not in event:
                other.append(line)
                continue
            if event["type"] == "result":
                result = _with_last_message(event, result)
            elif event["type"] == "rate_limit_event":
                limits = event.get("rate_limit_info")
            idle.saw(event, result)
            if on_event:
                on_event(event)
        idle.close()
        process.wait()
        drain.join()
    if idle.ended and on_event:
        on_event({"type": _LOOP_EVENT, "text": _IdleEnd.NOTICE})
    extra = {"rate_limit_info": limits} if limits else {}
    extra |= {"ended_by_loop": True} if idle.ended else {}
    return subprocess.CompletedProcess(
        list(args),
        0 if idle.ended else process.returncode,
        json.dumps({**result, **extra}, ensure_ascii=False)
        if result
        else "".join(other),
        "".join(errors),
    )


class _IdleEnd:
    """Ends a session that stays open, idle, after its `DECKZ-LOOP:` line.

    A headless session lives as long as something of its own is pending. Its
    subagents and commands print events as they work; a scheduled wakeup
    prints nothing until it fires. So after each turn that leaves the session
    with its line given (`saw`), a timer starts, which any later sign of work
    stops and the next such turn starts again.
    """

    NOTICE = (
        "the session gave its DECKZ-LOOP line and stayed open with nothing"
        " running (a scheduled wakeup?): ended by the loop"
    )

    def __init__(self, process: "subprocess.Popen[str]", grace: timedelta) -> None:
        self.ended = False
        self._process = process
        self._grace = grace.total_seconds()
        self._timer: Timer | None = None

    def saw(self, event: dict, result: dict | None) -> None:
        """Take one event of the session's stream into account.

        Args:
            event: The event.
            result: The session's result so far (`_with_last_message`).
        """
        if event["type"] not in ("result", "assistant", "user"):
            return
        self.close()
        if event["type"] != "result" or not result or result.get("is_error"):
            return
        if _MARKER.search(str(result.get("result") or "")):
            self._timer = Timer(self._grace, self._end)
            self._timer.daemon = True
            self._timer.start()

    def close(self) -> None:
        """Stop the timer, if one runs."""
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _end(self) -> None:
        self.ended = True
        self._process.terminate()
        try:
            self._process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self._process.kill()


def _with_last_message(event: dict, previous: dict | None) -> dict:
    """A `result` event, with the message that stands as the session's last.

    Args:
        event: The `result` event of the turn that just ended.
        previous: What this function gave for the turn before, if any.

    Returns:
        `event`, with `previous`'s message instead of its own when it isn't
        an error and its turn said nothing, or followed the session's
        `DECKZ-LOOP:` line without giving one: the answer to a notice or to a
        wakeup that came after the end.
    """
    if event.get("is_error") or not previous:
        return event
    said, before = (str(e.get("result") or "") for e in (event, previous))
    if said and (_MARKER.search(said) or not _MARKER.search(before)):
        return event
    return {**event, "result": before}


def _usage(data: dict, now: datetime) -> tuple[datetime | None, dict[str, float]]:
    """The usage figures `run_session` kept with a session's result.

    Returns:
        When the window that binds resets, and the share spent of each window
        (`five_hour`, `seven_day`) that gives one.
    """
    info = data.get("rate_limit_info")
    if not isinstance(info, dict):
        return None, {}
    resets = info.get("resetsAt")
    reset = None
    if isinstance(resets, int | float) and resets > 0:
        reset = max(datetime.fromtimestamp(resets, now.tzinfo), now)
    windows = info.get("unifiedWindows")
    used = {
        name: float(window["utilization"])
        for name, window in (windows if isinstance(windows, dict) else {}).items()
        if isinstance(window, dict)
        and isinstance(window.get("utilization"), int | float)
    }
    return reset, used


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
        Its outcome: `limit` when the account's usage limit stopped it (its
        reset is the time its message gives, or else the one its events gave),
        `error` when claude failed, reported another error, or the final
        message has no `DECKZ-LOOP:` line (`cut` when claude's stderr says it
        stopped the session's background tasks: the session was waiting for
        them); the last such line otherwise.
    """
    now = now or datetime.now().astimezone()

    def outcome(
        status: Status,
        reason: str,
        result: str = "",
        data: dict | None = None,
        resets_at: datetime | None = None,
    ) -> SessionOutcome:
        data = data or {}
        cost = data.get("total_cost_usd")
        used = _usage(data, now)[1]
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
            window_used=used.get("five_hour"),
            week_used=used.get("seven_day"),
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
                limit_reset(result, now) or _usage(data, now)[0],
            )
        subtype = data.get("subtype") or f"exit code {completed.returncode}"
        return outcome("error", f"{subtype}: {result.strip()[-300:]}", result, data)
    markers = list(_MARKER.finditer(result))
    if not markers:
        reason = "the session gave no DECKZ-LOOP line"
        if cut := _CUT.search(completed.stderr or ""):
            return outcome("cut", f"{reason}: {cut[0]}", result, data)
        return outcome("error", reason, result, data)
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
    until: datetime,
    sleep: Callable[[float], None],
    clock: Callable[[], datetime],
    stopped: Callable[[], bool],
) -> bool:
    """Sleep until the clock shows `until`, however long the machine was suspended.

    Returns:
        Whether it slept that long: not when `stopped` said to end meanwhile,
        which it is asked every minute.
    """
    while (left := (until - clock()).total_seconds()) > 0:
        if stopped():
            return False
        sleep(min(left, 60))
    return True


def _wait_for_reset(
    outcome: SessionOutcome,
    polled: timedelta,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], datetime],
    stopped: Callable[[], bool],
    on_wait: Callable[[SessionOutcome, datetime], None] | None,
) -> timedelta | None:
    """Sleep until the usage limit that stopped `outcome`'s session has reset.

    Returns:
        How long the loop has now waited without knowing when the limit
        resets (what `polled` becomes). None when the session isn't to be
        reopened: the reset is too far (`_limit_wait`), or a stop was
        requested during the wait.
    """
    wait = _limit_wait(outcome, clock(), polled)
    if wait is None:
        return None
    until = clock() + wait
    if on_wait:
        on_wait(outcome, until)
    if not _sleep_until(until, sleep, clock, stopped):
        return None
    return polled + wait if outcome.resets_at is None else timedelta()


def running_loops(git_dir: Path) -> list[Path]:
    """The loops running in a repository.

    Args:
        git_dir: The repository (a worktree is one of its own: a loop started
            in it runs there).

    Returns:
        The log directory of each: those whose lock a process holds.
    """
    import fcntl

    running = []
    for lock in sorted((git_dir / ".run" / "agent-loop").glob("*/lock")):
        with lock.open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                running.append(lock.parent)
    return running


def stop_requested(log_dir: Path) -> bool:
    """Whether the loop that logs in `log_dir` was asked to stop (`request_stop`).

    Returns:
        Whether its `stop` file is there.
    """
    return (log_dir / "stop").exists()


def request_stop(git_dir: Path) -> list[Path]:
    """Ask the loops running in a repository to end after their current session.

    Each starts no fresh session once the one at work has ended its share,
    and one waiting for a usage limit ends within a minute.

    Args:
        git_dir: The repository.

    Returns:
        The log directory of each loop asked.

    Raises:
        DeckzError: When no loop runs there.
    """
    loops = running_loops(git_dir)
    if not loops:
        msg = (
            f"no deckz agent loop is running in {git_dir}: a loop started with"
            " --workdir is stopped with the same --workdir (a worktree's,"
            " ../<repository>--<name>)"
        )
        raise DeckzError(msg)
    for log_dir in loops:
        (log_dir / "stop").touch()
    return loops


def _keep(completed: "subprocess.CompletedProcess[str]", log: Path) -> Path:
    """Write a session's result to `log`, and its stderr, if any, next to it.

    Returns:
        `log`.
    """
    log.write_text(completed.stdout or "", encoding="utf8")
    if completed.stderr:
        log.with_suffix(".err").write_text(completed.stderr, encoding="utf8")
    return log


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
    on_reopen: Callable[[SessionOutcome], None] | None = None,
    on_event: Callable[[dict], None] | None = None,
    runner: Runner | None = None,
    sleep: Callable[[float], None] = _sleep,
    clock: Callable[[], datetime] | None = None,
) -> list[SessionOutcome]:
    """Run `prompt` in one fresh session after another, until one doesn't say continue.

    A `cut` session (Claude Code stopped the background tasks it was waiting
    for) is reopened at once (`--resume`, `RESUME_PROMPT`), once: cut again,
    it ends the loop.

    Once asked to stop (`request_stop`), the loop starts no fresh session
    and ends a wait for a usage limit; `stop_requested`, on the last
    outcome's log directory, tells such an end from the others.

    Args:
        prompt: What every session is asked, `PROTOCOL` appended.
        git_dir: The repository the sessions run in.
        max_sessions: The most sessions to start; reopening one doesn't
            count.
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
        on_reopen: Called with a `cut` session's outcome before the session
            is reopened.
        on_event: Called with each event of each session's stream as it
            comes (`describe_event` reads one).
        runner: `run_session` by default, or a stand-in in tests.
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
    outcomes: list[SessionOutcome] = []
    with file_lock(log_dir / "lock", f"another loop logs in {log_dir}: waiting"):
        _run_sessions(
            outcomes,
            log_dir=log_dir,
            git_dir=git_dir,
            max_sessions=max_sessions,
            command=command,
            prompt=full_prompt,
            wait_on_limit=wait_on_limit,
            resume=resume,
            on_session=on_session,
            on_wait=on_wait,
            on_reopen=on_reopen,
            on_event=on_event,
            run=runner or run_session,
            sleep=sleep,
            clock=clock or (lambda: datetime.now().astimezone()),
        )
    return outcomes


def _run_sessions(
    outcomes: list[SessionOutcome],
    *,
    log_dir: Path,
    git_dir: Path,
    max_sessions: int,
    command: Sequence[str],
    prompt: str,
    wait_on_limit: bool,
    resume: str | None,
    on_session: Callable[[SessionOutcome], None] | None,
    on_wait: Callable[[SessionOutcome, datetime], None] | None,
    on_reopen: Callable[[SessionOutcome], None] | None,
    on_event: Callable[[dict], None] | None,
    run: Runner,
    sleep: Callable[[float], None],
    clock: Callable[[], datetime],
) -> None:
    """Run the sessions of `agent_loop`, which holds the loop's lock meanwhile.

    Each run's outcome is added to `outcomes`, and its result kept in
    `log_dir`. `prompt` is what a fresh session is asked, `PROTOCOL`
    included, and `run` what runs one session; the other arguments are
    `agent_loop`'s.
    """

    def stopped() -> bool:
        return stop_requested(log_dir)

    started = 0
    polled = timedelta()
    cut: int | None = None  # the last session reopened after a cut, as `started`
    while resume or (started < max_sessions and not stopped()):
        number = len(outcomes) + 1
        started += resume is None
        start = monotonic()
        completed = run(
            [*command, "--resume", resume] if resume else list(command),
            prompt=RESUME_PROMPT if resume else prompt,
            cwd=git_dir,
            on_event=on_event,
        )
        outcome = parse_session(
            number,
            completed,
            duration_s=monotonic() - start,
            log=_keep(completed, log_dir / f"session-{number:02}.json"),
            now=clock(),
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
        if outcome.status == "cut" and outcome.session_id and cut != started:
            cut = started
            if on_reopen:
                on_reopen(outcome)
            resume = outcome.session_id
            continue
        if outcome.status != "limit" or not wait_on_limit:
            break
        waited = _wait_for_reset(
            outcome, polled, sleep=sleep, clock=clock, stopped=stopped, on_wait=on_wait
        )
        if waited is None:
            break
        polled = waited
        resume = outcome.session_id
