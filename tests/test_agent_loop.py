import json
import os
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pytest import approx, raises

from deckz.agent_loop import (
    LIMIT_POLL,
    MAX_LIMIT_WAIT,
    PROTOCOL,
    RESUME_PROMPT,
    agent_loop,
    claude_command,
    limit_reset,
    parse_session,
)
from deckz.cli import main


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
        "claude", "-p", "--output-format", "json",
        "--permission-mode", "auto", "--model", "opus",
    ]  # fmt: skip
    assert calls[0]["input"] == "Do one block" + PROTOCOL
    assert calls[0]["cwd"] == tmp_path
    (log_dir,) = (tmp_path / ".run" / "agent-loop").iterdir()
    assert (log_dir / "prompt.txt").read_text(encoding="utf8") == calls[0]["input"]
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
    assert calls[2]["input"] == RESUME_PROMPT
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
    assert calls[2]["input"] == "Do one block" + PROTOCOL


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
    assert calls[0]["input"] == RESUME_PROMPT
    assert calls[1]["args"] == ["claude"]
    assert calls[1]["input"] == "Do one block" + PROTOCOL
