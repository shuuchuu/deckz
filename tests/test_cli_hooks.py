import json
import subprocess
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from typing import Any

from pygit2 import init_repository
from pytest import LogCaptureFixture, MonkeyPatch, fixture, raises

from deckz.cli import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _stdin(monkeypatch: MonkeyPatch, text: str) -> None:
    import sys

    monkeypatch.setattr(sys, "stdin", StringIO(text))


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            *args,
        ],
        cwd=cwd,
        check=True,
    )


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Iterator[Path]:
    import appdirs

    init_repository(str(tmp_path), initial_head="main")
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_path))
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def test_check_commit_msg_allows_a_synced_commit(repo: Path) -> None:
    _write(repo / "content" / "topic" / "topic.md", "fr")
    _write(repo / "content" / "topic" / "en" / "topic.md", "en")
    _git(repo, "add", "-A")
    message = repo / "msg.txt"
    message.write_text("Add topic\n", encoding="utf-8")

    main(("hooks", "check-commit-msg", str(message)))  # Should not raise.


def _one_sided(repo: Path) -> None:
    """Commit a fr/en pair, then stage a change to its French side only."""
    _write(repo / "content" / "topic" / "topic.md", "fr v1")
    _write(repo / "content" / "topic" / "en" / "topic.md", "en v1")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "Add topic")
    _write(repo / "content" / "topic" / "topic.md", "fr v2")
    _git(repo, "add", "-A")


def test_check_commit_msg_marks_a_one_sided_change_pending(
    repo: Path, caplog: LogCaptureFixture
) -> None:
    _one_sided(repo)
    message = repo / "msg.txt"
    message.write_text("Update fr\n", encoding="utf-8")

    main(("hooks", "check-commit-msg", str(message)))

    assert message.read_text(encoding="utf-8") == "Update fr\n\nLang-sync: pending\n"
    assert "content/topic/topic.md (not content/topic/en/topic.md)" in caplog.text
    assert "deckz i18n stale" in caplog.text
    assert "deckz i18n mark-synced" in caplog.text


def test_check_commit_msg_marks_above_the_editor_comments(repo: Path) -> None:
    _one_sided(repo)
    message = repo / "msg.txt"
    message.write_text(
        "Update fr\n\n# Lang-sync: en-only (a comment, not read)\n"
        "# ------------------------ >8 ------------------------\n"
        "+Lang-sync: fr-only (in the diff, not read)\n",
        encoding="utf-8",
    )

    main(("hooks", "check-commit-msg", str(message)))

    assert message.read_text(encoding="utf-8").startswith(
        "Update fr\n\nLang-sync: pending\n\n# Lang-sync: en-only"
    )


def test_check_commit_msg_refuses_a_lang_sync_line_not_read(
    repo: Path, caplog: LogCaptureFixture
) -> None:
    _one_sided(repo)
    message = repo / "msg.txt"
    text = "Fix typo\n\nLang-sync: fr only (typo)\n"
    message.write_text(text, encoding="utf-8")

    with raises(SystemExit) as exc_info:
        main(("hooks", "check-commit-msg", str(message)))

    assert exc_info.value.code == 1
    assert "Lang-sync: fr only (typo)\nisn't read" in caplog.text
    assert message.read_text(encoding="utf-8") == text


def test_hooks_install_then_commit_runs_the_hook(repo: Path) -> None:
    main(("hooks", "install"))
    _write(repo / "deckz.yml", "{}\n")
    _git(repo, "add", "-A")

    _git(repo, "commit", "-m", "Init")  # Should not raise (nothing one-sided).
    _one_sided(repo)

    _git(repo, "commit", "-m", "Update fr")

    message = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert message.strip() == "Update fr\n\nLang-sync: pending"


def test_hooks_install_also_writes_claude_settings(repo: Path) -> None:
    main(("hooks", "install"))

    settings = json.loads(
        (repo / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    assert set(settings["hooks"]) == {
        "PreToolUse",
        "PostToolUse",
        "SessionStart",
        "Stop",
    }


def test_pre_bash_denies_staging_everything(
    repo: Path, capsys: Any, monkeypatch: MonkeyPatch
) -> None:
    payload = json.dumps({"tool_input": {"command": "git add -A"}, "cwd": str(repo)})
    _stdin(monkeypatch, payload)

    main(("hooks", "pre-bash"))

    output = json.loads(capsys.readouterr().out)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pre_bash_is_silent_on_a_harmless_command(
    repo: Path, capsys: Any, monkeypatch: MonkeyPatch
) -> None:
    payload = json.dumps({"tool_input": {"command": "echo hi"}, "cwd": str(repo)})
    _stdin(monkeypatch, payload)

    main(("hooks", "pre-bash"))

    assert capsys.readouterr().out == ""


def test_pre_bash_never_raises_on_garbage_stdin(
    repo: Path, capsys: Any, monkeypatch: MonkeyPatch
) -> None:
    _stdin(monkeypatch, "not json")

    main(("hooks", "pre-bash"))  # Should not raise.

    assert capsys.readouterr().out == ""


def test_post_edit_is_silent_on_a_clean_file(
    repo: Path, capsys: Any, monkeypatch: MonkeyPatch
) -> None:
    _write(repo / "content" / "topic" / "topic.md", "# Topic\n\nHello.\n")
    _write(repo / "deckz.yml", "pandoc_command: [pandoc, -f, markdown, -t, typst]\n")
    payload = json.dumps(
        {"tool_input": {"file_path": str(repo / "content" / "topic" / "topic.md")}}
    )
    _stdin(monkeypatch, payload)

    main(("hooks", "post-edit"))

    assert capsys.readouterr().out == ""


def test_session_start_then_stop_is_silent_without_a_change(
    repo: Path, capsys: Any, monkeypatch: MonkeyPatch
) -> None:
    _stdin(monkeypatch, json.dumps({"session_id": "s1"}))
    main(("hooks", "session-start"))

    _stdin(monkeypatch, json.dumps({"session_id": "s1"}))
    main(("hooks", "stop"))

    assert capsys.readouterr().out == ""


def test_check_commits_lists_a_commit_with_no_trailer(
    repo: Path, caplog: LogCaptureFixture
) -> None:
    _one_sided(repo)
    _git(repo, "commit", "-m", "Update fr")

    main(("hooks", "check-commits", "HEAD~1..HEAD"))  # Should not raise.

    assert "leave a translation pending" in caplog.text
    assert "Update fr" in caplog.text


def test_check_commits_refuses_a_lang_sync_line_not_read(
    repo: Path, caplog: LogCaptureFixture
) -> None:
    _one_sided(repo)
    _git(repo, "commit", "-m", "Fix typo\n\nLang-sync: fronly (typo)")

    with raises(SystemExit) as exc_info:
        main(("hooks", "check-commits", "HEAD~1..HEAD"))

    assert exc_info.value.code == 1
    assert "Fix typo: Lang-sync: fronly (typo)" in caplog.text
    assert "deckz i18n mark-synced" in caplog.text


def test_check_commits_accepts_a_trailer(repo: Path) -> None:
    _write(repo / "content" / "topic" / "topic.md", "fr v1")
    _write(repo / "content" / "topic" / "en" / "topic.md", "en v1")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "Add topic")
    _write(repo / "content" / "topic" / "topic.md", "fr v2")
    _git(repo, "commit", "-am", "Fix typo\n\nLang-sync: fr-only (typo)")

    main(("hooks", "check-commits", "HEAD~1..HEAD"))  # Should not raise.
