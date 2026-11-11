import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pytest import approx, raises

from deckz.agent_loop import (
    BACKGROUND_WAIT_VARIABLE,
    LIMIT_POLL,
    MAX_LIMIT_WAIT,
    PROTOCOL,
    RESUME_PROMPT,
    agent_loop,
    claude_command,
    describe_event,
    limit_reset,
    parse_session,
    request_stop,
    run_session,
    running_loops,
    session_environment,
    stop_requested,
)
from deckz.cli import main
from deckz.exceptions import DeckzError


def _completed(
    result: str, *, is_error: bool = False, code: int = 0, stderr: str = ""
) -> "subprocess.CompletedProcess[str]":
    stdout = json.dumps(
        {
            "result": result,
            "is_error": is_error,
            "subtype": "error_during_execution" if is_error else "success",
            "session_id": "abc",
            "total_cost_usd": 1.5,
        }
    )
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_parse_session_reads_the_last_marker(tmp_path: Path) -> None:
    outcome = parse_session(
        1,
        _completed("Block done.\nDECKZ-LOOP: continue\n"),
        duration_s=2.0,
        log=tmp_path / "l.json",
    )
    assert outcome.status == "continue"
    assert outcome.result == "Block done."
    assert outcome.session_id == "abc"
    assert outcome.cost_usd == approx(1.5)

    stop = parse_session(
        2,
        _completed("DECKZ-LOOP: continue\nthen\nDECKZ-LOOP: stop needs a GPU"),
        duration_s=0,
        log=tmp_path / "l.json",
    )
    assert (stop.status, stop.reason) == ("stop", "needs a GPU")


def test_parse_session_failures(tmp_path: Path) -> None:
    log = tmp_path / "l.json"
    no_marker = parse_session(1, _completed("done, I think"), duration_s=0, log=log)
    assert no_marker.status == "error"
    assert "no DECKZ-LOOP line" in no_marker.reason

    failed = parse_session(
        1, _completed("API Error: 500", is_error=True), duration_s=0, log=log
    )
    assert failed.status == "error"
    assert "API Error: 500" in failed.reason

    crashed = subprocess.CompletedProcess([], 1, "", "Error: not logged in\n")
    outcome = parse_session(1, crashed, duration_s=0, log=log)
    assert outcome.status == "error"
    assert outcome.reason == "claude exited with code 1: Error: not logged in"


def test_agent_loop_runs_until_done(tmp_path: Path) -> None:
    answers = iter(["a\nDECKZ-LOOP: continue", "b\nDECKZ-LOOP: done", "unused"])
    calls: list[dict[str, Any]] = []

    def runner(args: list[str], **kwargs: Any) -> "subprocess.CompletedProcess[str]":
        calls.append({"args": args, **kwargs})
        return _completed(next(answers))

    seen: list[int] = []
    outcomes = agent_loop(
        "Do one block",
        git_dir=tmp_path,
        max_sessions=5,
        command=claude_command(model="opus"),
        on_session=lambda o: seen.append(o.number),
        runner=runner,
    )
    assert [o.status for o in outcomes] == ["continue", "done"]
    assert seen == [1, 2]
    assert calls[0]["args"] == [
        "claude", "-p", "--output-format", "stream-json", "--verbose",
        "--permission-mode", "auto", "--model", "opus",
    ]  # fmt: skip
    assert calls[0]["prompt"] == "Do one block" + PROTOCOL
    assert calls[0]["cwd"] == tmp_path
    (log_dir,) = (tmp_path / ".run" / "agent-loop").iterdir()
    assert (log_dir / "prompt.txt").read_text(encoding="utf8") == calls[0]["prompt"]
    assert json.loads((log_dir / "session-02.json").read_text())["result"].startswith(
        "b"
    )


def test_agent_loop_stops_at_max_sessions(tmp_path: Path) -> None:
    outcomes = agent_loop(
        "p",
        git_dir=tmp_path,
        max_sessions=2,
        command=["claude"],
        runner=lambda *a, **k: _completed("DECKZ-LOOP: continue"),
    )
    assert len(outcomes) == 2


def _fake_claude(bin_dir: Path, results: list[str]) -> None:
    """A `claude` that answers each call with the next of `results`."""
    bin_dir.mkdir()
    (bin_dir / "answers.json").write_text(json.dumps(results), encoding="utf8")
    script = bin_dir / "claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "sys.stdin.read()\n"
        f"p = pathlib.Path({str(bin_dir / 'answers.json')!r})\n"
        "answers = json.loads(p.read_text())\n"
        "p.write_text(json.dumps(answers[1:]))\n"
        "print(json.dumps({'result': answers[0], 'is_error': False,"
        " 'session_id': 's', 'total_cost_usd': 0.5}))\n",
        encoding="utf8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def test_cli_agent_loop(tmp_path: Path, capsys: Any, monkeypatch: Any) -> None:
    repo = _repo(tmp_path)
    _fake_claude(
        tmp_path / "bin", ["one\nDECKZ-LOOP: continue", "all done\nDECKZ-LOOP: done"]
    )
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    main(("agent", "loop", "Do one block", "--workdir", str(repo)))
    out = capsys.readouterr().out
    assert "all done" in out
    assert "last session: done" in out


def test_cli_agent_loop_exits_1_on_stop(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    repo = _repo(tmp_path)
    _fake_claude(tmp_path / "bin", ["DECKZ-LOOP: stop the plan asks the user"])
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    with raises(SystemExit) as exit_info:
        main(("agent", "loop", "p", "--workdir", str(repo), "--json"))
    assert exit_info.value.code == 1
    (outcome,) = json.loads(capsys.readouterr().out)
    assert outcome["status"] == "stop"
    assert outcome["reason"] == "the plan asks the user"


_PARIS = ZoneInfo("Europe/Paris")
_LIMIT_MESSAGE = "You've hit your 5-hour limit · resets 9pm (Europe/Paris)"


def _limited(
    message: str = _LIMIT_MESSAGE, *, session_id: str = "abc"
) -> "subprocess.CompletedProcess[str]":
    stdout = json.dumps(
        {
            "result": message,
            "is_error": True,
            "subtype": "success",
            "api_error": "usage_limit_reached",
            "api_error_status": 429,
            "session_id": session_id,
            "total_cost_usd": 3.0,
        }
    )
    return subprocess.CompletedProcess([], 1, stdout, "")


def test_limit_reset() -> None:
    now = datetime(2026, 11, 10, 18, 45, tzinfo=_PARIS)
    assert limit_reset(_LIMIT_MESSAGE, now) == datetime(2026, 11, 10, 21, tzinfo=_PARIS)
    # Read in the zone the message names, whatever the clock's.
    assert limit_reset(_LIMIT_MESSAGE, now.astimezone(UTC)) == datetime(
        2026, 11, 10, 20, tzinfo=UTC
    )
    assert limit_reset("resets 2:30am", now) == datetime(
        2026, 11, 11, 2, 30, tzinfo=_PARIS
    )
    assert limit_reset("resets 12am", now) == datetime(2026, 11, 11, tzinfo=_PARIS)
    assert limit_reset("will reset at 12pm", now) == datetime(
        2026, 11, 11, 12, tzinfo=_PARIS
    )
    # Minutes ago: it has just reset, not tomorrow.
    just_after = datetime(2026, 11, 10, 21, 3, tzinfo=_PARIS)
    assert limit_reset(_LIMIT_MESSAGE, just_after) == just_after
    weekly = "You've hit your weekly limit · resets Nov 14, 9am (Europe/Paris)"
    assert limit_reset(weekly, now) == datetime(2026, 11, 14, 9, tzinfo=_PARIS)
    assert limit_reset("resets Jan 2, 9am", now) == datetime(
        2027, 1, 2, 9, tzinfo=_PARIS
    )
    for unreadable in (
        "You've hit your limit",
        "resets in 3 hours",
        "resets 13pm",
        "resets 9pm (Nowhere/Atlantis)",
        "resets Foo 3, 9am",
    ):
        assert limit_reset(unreadable, now) is None, unreadable


def test_parse_session_usage_limit(tmp_path: Path) -> None:
    now = datetime(2026, 11, 10, 18, 45, tzinfo=_PARIS)
    outcome = parse_session(
        3, _limited(), duration_s=0, log=tmp_path / "l.json", now=now
    )
    assert (outcome.status, outcome.reason) == ("limit", _LIMIT_MESSAGE)
    assert outcome.resets_at == datetime(2026, 11, 10, 21, tzinfo=_PARIS)
    assert outcome.session_id == "abc"

    # Without the structured field, the message is enough.
    worded = parse_session(
        1,
        _completed("You've hit your limit", is_error=True),
        duration_s=0,
        log=tmp_path / "l.json",
        now=now,
    )
    assert (worded.status, worded.resets_at) == ("limit", None)


class _Clock:
    """A clock that only the loop's sleeps move."""

    def __init__(self, now: datetime) -> None:
        self.now = now
        self.slept = 0.0

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept += seconds
        self.now += timedelta(seconds=seconds)


def _scripted(
    answers: list["subprocess.CompletedProcess[str]"], calls: list[dict[str, Any]]
) -> Any:
    queue = iter(answers)

    def runner(args: list[str], **kwargs: Any) -> "subprocess.CompletedProcess[str]":
        calls.append({"args": args, **kwargs})
        return next(queue)

    return runner


def test_agent_loop_stops_at_a_limit_unless_asked_to_wait(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    clock = _Clock(datetime(2026, 11, 10, 18, 45, tzinfo=_PARIS))
    outcomes = agent_loop(
        "p",
        git_dir=tmp_path,
        max_sessions=5,
        command=["claude"],
        runner=_scripted([_limited()], calls),
        sleep=clock.sleep,
        clock=clock,
    )
    assert [o.status for o in outcomes] == ["limit"]
    assert clock.slept == 0


def test_agent_loop_waits_for_the_reset_and_reopens_the_session(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    clock = _Clock(datetime(2026, 11, 10, 18, 45, tzinfo=_PARIS))
    waits: list[tuple[int, datetime]] = []
    outcomes = agent_loop(
        "Do one block",
        git_dir=tmp_path,
        max_sessions=2,
        command=["claude"],
        wait_on_limit=True,
        on_wait=lambda outcome, until: waits.append((outcome.number, until)),
        runner=_scripted(
            [
                _completed("a\nDECKZ-LOOP: continue"),
                _limited(session_id="cut"),
                _completed("b\nDECKZ-LOOP: continue"),
                _completed("unused"),
            ],
            calls,
        ),
        sleep=clock.sleep,
        clock=clock,
    )
    # The reopened run isn't one of the two sessions --max-sessions allows.
    assert [o.status for o in outcomes] == ["continue", "limit", "continue"]
    assert waits == [(2, datetime(2026, 11, 10, 21, 1, tzinfo=_PARIS))]
    assert clock.now == datetime(2026, 11, 10, 21, 1, tzinfo=_PARIS)
    assert calls[1]["args"] == ["claude"]
    assert calls[2]["args"] == ["claude", "--resume", "cut"]
    assert calls[2]["prompt"] == RESUME_PROMPT
    assert (tmp_path / ".run" / "agent-loop").is_dir()
    (log_dir,) = (tmp_path / ".run" / "agent-loop").iterdir()
    assert (log_dir / "session-03.json").exists()


def test_agent_loop_does_not_wait_for_a_weekly_limit(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    clock = _Clock(datetime(2026, 11, 10, 18, 45, tzinfo=_PARIS))
    outcomes = agent_loop(
        "p",
        git_dir=tmp_path,
        max_sessions=5,
        command=["claude"],
        wait_on_limit=True,
        runner=_scripted(
            [_limited("You've hit your weekly limit · resets Nov 14, 9am")], calls
        ),
        sleep=clock.sleep,
        clock=clock,
    )
    assert [o.status for o in outcomes] == ["limit"]
    assert clock.slept == 0


def test_agent_loop_polls_when_the_reset_time_is_unknown(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    clock = _Clock(datetime(2026, 11, 10, 18, 45, tzinfo=_PARIS))
    outcomes = agent_loop(
        "p",
        git_dir=tmp_path,
        max_sessions=1,
        command=["claude"],
        wait_on_limit=True,
        runner=_scripted(
            [
                _limited("You've hit your limit"),
                _limited("You've hit your limit"),
                _completed("DECKZ-LOOP: done"),
            ],
            calls,
        ),
        sleep=clock.sleep,
        clock=clock,
    )
    assert [o.status for o in outcomes] == ["limit", "limit", "done"]
    assert clock.slept == 2 * LIMIT_POLL.total_seconds()
    assert [c["args"] for c in calls[1:]] == [["claude", "--resume", "abc"]] * 2

    # Never for longer than MAX_LIMIT_WAIT.
    calls.clear()
    clock = _Clock(datetime(2026, 11, 10, 18, 45, tzinfo=_PARIS))
    outcomes = agent_loop(
        "p",
        git_dir=tmp_path,
        max_sessions=1,
        command=["claude"],
        wait_on_limit=True,
        runner=_scripted([_limited("You've hit your limit")] * 100, calls),
        sleep=clock.sleep,
        clock=clock,
    )
    assert outcomes[-1].status == "limit"
    assert clock.slept == MAX_LIMIT_WAIT.total_seconds()


def test_agent_loop_starts_afresh_when_the_session_cannot_be_reopened(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    clock = _Clock(datetime(2026, 11, 10, 18, 45, tzinfo=_PARIS))
    gone = subprocess.CompletedProcess(
        [], 1, "", "No conversation found with session ID: cut\n"
    )
    outcomes = agent_loop(
        "Do one block",
        git_dir=tmp_path,
        max_sessions=3,
        command=["claude"],
        wait_on_limit=True,
        runner=_scripted(
            [_limited(session_id="cut"), gone, _completed("DECKZ-LOOP: done")], calls
        ),
        sleep=clock.sleep,
        clock=clock,
    )
    assert [o.status for o in outcomes] == ["limit", "error", "done"]
    assert calls[2]["args"] == ["claude"]
    assert calls[2]["prompt"] == "Do one block" + PROTOCOL


def test_cli_agent_loop_reports_a_limit(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    repo = _repo(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'result': 'You have hit your weekly limit, resets"
        " Jan 1, 9am', 'is_error': True, 'api_error': 'usage_limit_reached',"
        " 'session_id': 's'}))\n"
        "sys.exit(1)\n",
        encoding="utf8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    with raises(SystemExit) as exit_info:
        main(("agent", "loop", "p", "--workdir", str(repo), "--wait-on-limit"))
    assert exit_info.value.code == 1
    out = capsys.readouterr().out
    assert "last session: limit" in out
    assert "not waited for" in out


def test_agent_loop_reopens_a_given_session_first(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    outcomes = agent_loop(
        "Do one block",
        git_dir=tmp_path,
        max_sessions=1,
        command=["claude"],
        resume="cut",
        runner=_scripted(
            [_completed("DECKZ-LOOP: continue"), _completed("DECKZ-LOOP: continue")],
            calls,
        ),
    )
    # The reopened session, then the one fresh session --max-sessions allows.
    assert [o.status for o in outcomes] == ["continue", "continue"]
    assert calls[0]["args"] == ["claude", "--resume", "cut"]
    assert calls[0]["prompt"] == RESUME_PROMPT
    assert calls[1]["args"] == ["claude"]
    assert calls[1]["prompt"] == "Do one block" + PROTOCOL


_STREAM = [
    {"type": "system", "subtype": "init", "tools": ["Bash"]},
    {
        "type": "assistant",
        "parent_tool_use_id": None,
        "message": {
            "content": [
                {"type": "thinking", "thinking": "hm"},
                {"type": "text", "text": "Je lis le plan.\n"},
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {"command": "git  status\n--short", "description": ""},
                },
                {
                    "type": "tool_use",
                    "name": "Agent",
                    "input": {"model": "opus", "description": "qa-fix unité 1"},
                },
            ]
        },
    },
    {
        "type": "assistant",
        "parent_tool_use_id": "toolu_1",
        "message": {"content": [{"type": "text", "text": "a subagent speaks"}]},
    },
    {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
    {
        "type": "rate_limit_event",
        "rate_limit_info": {
            "status": "allowed",
            "resetsAt": 1794358800,
            "rateLimitType": "five_hour",
            "unifiedWindows": {
                "five_hour": {"utilization": 0.37, "resetsAt": 1794358800},
                "seven_day": {"utilization": 0.12, "resetsAt": 1794938400},
            },
        },
    },
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "Bloc fait.\nDECKZ-LOOP: continue",
        "session_id": "s1",
        "total_cost_usd": 2.0,
    },
]


def test_describe_event() -> None:
    assert [line for event in _STREAM for line in describe_event(event)] == [
        "Je lis le plan.",
        "→ Bash: git status --short",
        "→ Agent [opus]: qa-fix unité 1",
    ]
    long = {"type": "tool_use", "name": "Read", "input": {"file_path": "x" * 300}}
    (line,) = describe_event({"type": "assistant", "message": {"content": [long]}})
    assert len(line) == len("→ Read: ") + 120
    assert describe_event({"type": "assistant", "message": None}) == []


def _streaming_claude(bin_dir: Path, lines: list[str], code: int = 0) -> Path:
    """A `claude` that prints `lines`, then exits with `code`.

    Returns:
        The script.
    """
    bin_dir.mkdir()
    (bin_dir / "lines.json").write_text(json.dumps(lines), encoding="utf8")
    script = bin_dir / "claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "sys.stdin.read()\n"
        f"path = pathlib.Path({str(bin_dir / 'lines.json')!r})\n"
        "lines = json.loads(path.read_text())\n"
        "print(*lines, sep='\\n', flush=True)\n"
        "print('a warning', file=sys.stderr)\n"
        f"sys.exit({code})\n",
        encoding="utf8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_run_session_reads_the_stream(tmp_path: Path) -> None:
    script = _streaming_claude(
        tmp_path / "bin", [json.dumps(e, ensure_ascii=False) for e in _STREAM]
    )
    seen: list[str] = []
    completed = run_session(
        [str(script)],
        prompt="Do one block",
        cwd=tmp_path,
        on_event=lambda event: seen.extend(describe_event(event)),
    )
    assert seen[0] == "Je lis le plan."
    assert completed.returncode == 0
    assert completed.stderr == "a warning\n"
    data = json.loads(completed.stdout)
    assert data["session_id"] == "s1"
    windows = data["rate_limit_info"]["unifiedWindows"]
    assert windows["five_hour"]["utilization"] == approx(0.37)

    outcome = parse_session(1, completed, duration_s=1, log=tmp_path / "l.json")
    assert (outcome.status, outcome.result) == ("continue", "Bloc fait.")
    assert outcome.window_used == approx(0.37)
    assert outcome.week_used == approx(0.12)


def test_run_session_without_a_result_keeps_what_was_printed(tmp_path: Path) -> None:
    script = _streaming_claude(tmp_path / "bin", ["not json", '{"no": "type"}'], 1)
    completed = run_session([str(script)], prompt="p", cwd=tmp_path)
    assert completed.returncode == 1
    assert completed.stdout == 'not json\n{"no": "type"}\n'
    outcome = parse_session(1, completed, duration_s=0, log=tmp_path / "l.json")
    assert outcome.status == "error"
    assert outcome.reason == "claude exited with code 1: a warning"


def test_parse_session_takes_the_reset_from_the_events(tmp_path: Path) -> None:
    now = datetime(2026, 11, 10, 22, 0, tzinfo=_PARIS)
    reset = datetime(2026, 11, 11, 2, 0, tzinfo=_PARIS)
    stdout = json.dumps(
        {
            "result": "You've hit your limit",
            "is_error": True,
            "api_error": "usage_limit_reached",
            "session_id": "abc",
            "rate_limit_info": {"resetsAt": reset.timestamp(), "status": "rejected"},
        }
    )
    outcome = parse_session(
        1,
        subprocess.CompletedProcess([], 1, stdout, ""),
        duration_s=0,
        log=tmp_path / "l.json",
        now=now,
    )
    assert (outcome.status, outcome.resets_at) == ("limit", reset)
    assert outcome.window_used is None


def test_cli_agent_loop_shows_the_steps(
    tmp_path: Path, capsys: Any, caplog: Any, monkeypatch: Any
) -> None:
    repo = _repo(tmp_path)
    done = {**_STREAM[-1], "result": "Fini.\nDECKZ-LOOP: done"}
    _streaming_claude(
        tmp_path / "bin",
        [json.dumps(e, ensure_ascii=False) for e in [*_STREAM[:-1], done]],
    )
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    with caplog.at_level("INFO"):
        main(("agent", "loop", "p", "--workdir", str(repo)))
    assert "→ Agent [opus]: qa-fix unité 1" in caplog.text
    assert "usage: 5-hour window 37%, week 12%" in caplog.text
    assert "last session: done" in capsys.readouterr().out

    caplog.clear()
    with caplog.at_level("INFO"):
        main(("agent", "loop", "p", "--workdir", str(repo), "--no-steps"))
    assert "→ Agent" not in caplog.text
    assert "session 1: done" in caplog.text


_CUT_STDERR = (
    'Background tasks still running 10m after the last turn (subagent "Rédacteur'
    ' lab"); stopping them. Set CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 to wait'
    " indefinitely.\n"
)


def _cut(session_id: str = "abc") -> "subprocess.CompletedProcess[str]":
    """A session Claude Code ended while it waited for a subagent.

    Returns:
        The finished process, as `run_session` gives it.
    """
    stdout = json.dumps(
        {
            "result": "J'attends le rédacteur du TP.",
            "is_error": False,
            "subtype": "success",
            "session_id": session_id,
            "total_cost_usd": 5.0,
        }
    )
    return subprocess.CompletedProcess([], 0, stdout, _CUT_STDERR)


def test_session_environment_sets_the_background_wait() -> None:
    assert session_environment({"A": "b"}) == {
        "A": "b",
        BACKGROUND_WAIT_VARIABLE: "7200000",
    }
    # The user's own value is kept.
    assert session_environment({BACKGROUND_WAIT_VARIABLE: "0"}) == {
        BACKGROUND_WAIT_VARIABLE: "0"
    }


def test_run_session_gives_the_session_time_for_its_subagents(
    tmp_path: Path, monkeypatch: Any
) -> None:
    script = tmp_path / "claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'type': 'result', 'result':"
        f" os.environ.get({BACKGROUND_WAIT_VARIABLE!r})}}))\n",
        encoding="utf8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.delenv(BACKGROUND_WAIT_VARIABLE, raising=False)
    completed = run_session([str(script)], prompt="p", cwd=tmp_path)
    assert json.loads(completed.stdout)["result"] == "7200000"

    monkeypatch.setenv(BACKGROUND_WAIT_VARIABLE, "0")
    completed = run_session([str(script)], prompt="p", cwd=tmp_path)
    assert json.loads(completed.stdout)["result"] == "0"


def test_parse_session_cut_while_waiting_for_its_subagents(tmp_path: Path) -> None:
    log = tmp_path / "l.json"
    outcome = parse_session(2, _cut(), duration_s=0, log=log)
    assert outcome.status == "cut"
    assert outcome.reason == (
        "the session gave no DECKZ-LOOP line: Background tasks still running 10m"
        ' after the last turn (subagent "Rédacteur lab"); stopping them'
    )
    assert outcome.result == "J'attends le rédacteur du TP."
    assert outcome.session_id == "abc"

    # A session that gave its line is done, whatever was still running.
    said = _completed("Bloc fait.\nDECKZ-LOOP: continue", stderr=_CUT_STDERR)
    assert parse_session(1, said, duration_s=0, log=log).status == "continue"
    # And a failure stays one.
    failed = _completed("API Error: 500", is_error=True, stderr=_CUT_STDERR)
    assert parse_session(1, failed, duration_s=0, log=log).status == "error"


def test_agent_loop_reopens_a_cut_session_once(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    reopened: list[int] = []
    outcomes = agent_loop(
        "Do one block",
        git_dir=tmp_path,
        max_sessions=2,
        command=["claude"],
        on_reopen=lambda outcome: reopened.append(outcome.number),
        runner=_scripted(
            [
                _cut("first"),
                _completed("a\nDECKZ-LOOP: continue"),
                _cut("second"),
                _cut("second"),
                _completed("unused"),
            ],
            calls,
        ),
    )
    # Reopening isn't one of the two sessions --max-sessions allows; the
    # second session, cut again once reopened, ends the loop.
    assert [o.status for o in outcomes] == ["cut", "continue", "cut", "cut"]
    assert reopened == [1, 3]
    assert [c["args"] for c in calls] == [
        ["claude"],
        ["claude", "--resume", "first"],
        ["claude"],
        ["claude", "--resume", "second"],
    ]
    assert calls[1]["prompt"] == RESUME_PROMPT
    assert calls[2]["prompt"] == "Do one block" + PROTOCOL


def test_agent_loop_reopens_a_cut_session_once_across_a_limit(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    clock = _Clock(datetime(2026, 11, 10, 18, 45, tzinfo=_PARIS))
    outcomes = agent_loop(
        "p",
        git_dir=tmp_path,
        max_sessions=5,
        command=["claude"],
        wait_on_limit=True,
        runner=_scripted([_cut(), _limited(), _cut(), _completed("unused")], calls),
        sleep=clock.sleep,
        clock=clock,
    )
    assert [o.status for o in outcomes] == ["cut", "limit", "cut"]


def test_cli_agent_loop_reopens_a_cut_session(
    tmp_path: Path, capsys: Any, caplog: Any, monkeypatch: Any
) -> None:
    repo = _repo(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'type': 'result', 'result': 'J attends.',"
        " 'is_error': False, 'session_id': 's'}))\n"
        f"print({_CUT_STDERR!r}, end='', file=sys.stderr)\n",
        encoding="utf8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv(BACKGROUND_WAIT_VARIABLE, raising=False)
    with caplog.at_level("INFO"), raises(SystemExit) as exit_info:
        main(("agent", "loop", "p", "--workdir", str(repo)))
    assert exit_info.value.code == 1
    assert f"{BACKGROUND_WAIT_VARIABLE}=7200000 (deckz's default, in ms)" in caplog.text
    assert caplog.text.count("reopening session s") == 1
    out = capsys.readouterr().out
    assert "last session: cut: the session gave no DECKZ-LOOP line" in out
    assert "--resume s" in out
    (log_dir,) = (repo / ".run" / "agent-loop").iterdir()
    assert (log_dir / "session-02.err").read_text(encoding="utf8") == _CUT_STDERR


def test_run_session_keeps_the_last_message_through_a_silent_turn(
    tmp_path: Path,
) -> None:
    said = {**_STREAM[-1], "result": "Fini.\nDECKZ-LOOP: done", "total_cost_usd": 1.0}
    # The notice that a subagent finished, after its report: a turn of its own.
    silent = {**said, "result": "", "num_turns": 0, "total_cost_usd": 1.2}
    script = _streaming_claude(
        tmp_path / "bin", [json.dumps(e) for e in [*_STREAM[:-1], said, silent]]
    )
    completed = run_session([str(script)], prompt="p", cwd=tmp_path)
    outcome = parse_session(1, completed, duration_s=0, log=tmp_path / "l.json")
    assert (outcome.status, outcome.result) == ("done", "Fini.")
    assert outcome.cost_usd == approx(1.2)

    # A turn that says something else replaces it, and so does a failure.
    for last in (
        {**said, "result": "Rien de plus."},
        {**said, "result": "", "is_error": True},
    ):
        (tmp_path / "bin" / "lines.json").write_text(
            json.dumps([json.dumps(said), json.dumps(last)]), encoding="utf8"
        )
        completed = run_session([str(script)], prompt="p", cwd=tmp_path)
        outcome = parse_session(1, completed, duration_s=0, log=tmp_path / "l.json")
        assert outcome.status == "error"


def _stopping(
    git_dir: Path, answers: list["subprocess.CompletedProcess[str]"], calls: list[Any]
) -> Any:
    """A runner whose first session sees the loop asked to stop while it works.

    Returns:
        The runner, which answers each call with the next of `answers`.
    """
    queue = iter(answers)

    def runner(args: list[str], **kwargs: Any) -> "subprocess.CompletedProcess[str]":
        if not calls:
            (log_dir,) = running_loops(git_dir)
            assert request_stop(git_dir) == [log_dir]
        calls.append(args)
        return next(queue)

    return runner


def test_agent_loop_ends_after_the_session_at_work_when_asked_to_stop(
    tmp_path: Path,
) -> None:
    calls: list[Any] = []
    outcomes = agent_loop(
        "p",
        git_dir=tmp_path,
        max_sessions=5,
        command=["claude"],
        runner=_stopping(
            tmp_path, [_completed("a\nDECKZ-LOOP: continue"), _completed("no")], calls
        ),
    )
    assert [o.status for o in outcomes] == ["continue"]
    assert stop_requested(outcomes[-1].log.parent)

    # The loop has ended: nothing runs there any more, and a new loop isn't
    # stopped by the request the last one got.
    assert running_loops(tmp_path) == []
    with raises(DeckzError, match="no deckz agent loop is running"):
        request_stop(tmp_path)
    again = agent_loop(
        "p",
        git_dir=tmp_path / "other",
        max_sessions=1,
        command=["claude"],
        runner=lambda *a, **k: _completed("DECKZ-LOOP: done"),
    )
    assert not stop_requested(again[-1].log.parent)


def test_agent_loop_asked_to_stop_lets_a_cut_session_finish(tmp_path: Path) -> None:
    calls: list[Any] = []
    outcomes = agent_loop(
        "p",
        git_dir=tmp_path,
        max_sessions=5,
        command=["claude"],
        runner=_stopping(
            tmp_path,
            [_cut("s"), _completed("a\nDECKZ-LOOP: continue"), _completed("no")],
            calls,
        ),
    )
    assert [o.status for o in outcomes] == ["cut", "continue"]
    assert calls == [["claude"], ["claude", "--resume", "s"]]


def test_agent_loop_asked_to_stop_ends_a_wait_for_the_limit(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    clock = _Clock(datetime(2026, 11, 10, 18, 45, tzinfo=_PARIS))

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.slept == 120:
            request_stop(tmp_path)

    outcomes = agent_loop(
        "p",
        git_dir=tmp_path,
        max_sessions=5,
        command=["claude"],
        wait_on_limit=True,
        runner=_scripted([_limited(), _completed("unused")], calls),
        sleep=sleep,
        clock=clock,
    )
    # Two minutes into a wait of more than two hours: the session the limit
    # cut isn't reopened.
    assert [o.status for o in outcomes] == ["limit"]
    assert clock.slept == 120
    assert len(calls) == 1


def test_cli_agent_stop(tmp_path: Path, capsys: Any, monkeypatch: Any) -> None:
    repo = _repo(tmp_path)
    with raises(SystemExit) as exit_info:
        main(("agent", "stop", "--workdir", str(repo)))
    assert exit_info.value.code == 1

    # A session during which someone runs `deckz agent stop`, from another process.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    stop = "from deckz.cli import main; main(('agent', 'stop'))"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, subprocess, sys\n"
        "sys.stdin.read()\n"
        f"asked = subprocess.run([sys.executable, '-c', {stop!r}],"
        " capture_output=True, text=True, check=True).stdout\n"
        "print(json.dumps({'type': 'result', 'result': asked +"
        " 'DECKZ-LOOP: continue', 'is_error': False, 'session_id': 's'}))\n",
        encoding="utf8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    capsys.readouterr()
    main(("agent", "loop", "p", "--workdir", str(repo)))
    out = capsys.readouterr().out
    (log_dir,) = (repo / ".run" / "agent-loop").iterdir()
    assert f"asked to stop after its current session: {log_dir / 'stop'}" in out
    assert "stopped on request (deckz agent stop): more is left" in out
    assert not (log_dir / "session-02.json").exists()
