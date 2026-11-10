import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from pytest import approx, raises

from deckz.agent_loop import PROTOCOL, agent_loop, claude_command, parse_session
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

    limit = parse_session(
        1, _completed("usage limit reached", is_error=True), duration_s=0, log=log
    )
    assert limit.status == "error"
    assert "usage limit reached" in limit.reason

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
