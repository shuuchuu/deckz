import json
import subprocess
from pathlib import Path
from typing import Any

from pytest import raises

from deckz.cli import main


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(cwd),
            "-c",
            "user.name=test",
            "-c",
            "user.email=t@e.com",
            *list(args),
        ],
        check=True,
        capture_output=True,
    )


def _make_repo(tmp_path: Path) -> Path:
    main_dir = tmp_path / "repo"
    _git(tmp_path, "init", "-b", "main", str(main_dir))
    (main_dir / ".gitignore").write_text("/built/\n/.env\n", encoding="utf8")
    (main_dir / "deckz.yml").write_text("worktree:\n  seed: [built]\n", encoding="utf8")
    _git(main_dir, "add", "-A")
    _git(main_dir, "commit", "-m", "Initial")
    (main_dir / "built").mkdir()
    (main_dir / "built" / "fig.svg").write_text("<svg/>", encoding="utf8")
    (main_dir / ".env").write_text("", encoding="utf8")
    return main_dir


def test_add_list_and_remove(tmp_path: Path, capsys: Any, monkeypatch: Any) -> None:
    main_dir = _make_repo(tmp_path)
    monkeypatch.chdir(main_dir)

    # `deckz setup --check` then finds the git hooks missing in the worktree.
    with raises(SystemExit):
        main(("worktree", "add", "demo"))
    out = capsys.readouterr().out
    path = tmp_path / "repo--demo"
    assert f"created {path} on ws/demo" in out
    assert "copied 1 built file(s)" in out
    assert "linked .env" in out
    assert (path / "built" / "fig.svg").is_file()

    main(("worktree", "list", "--json"))
    (listed,) = json.loads(capsys.readouterr().out)
    assert listed["name"] == "demo"
    assert listed["changes"] == []

    main(("worktree", "remove", "demo"))
    assert "removed the worktree demo" in capsys.readouterr().out
    assert not path.exists()


def test_remove_exits_1_on_uncommitted_changes(
    tmp_path: Path, monkeypatch: Any
) -> None:
    main_dir = _make_repo(tmp_path)
    monkeypatch.chdir(main_dir)
    with raises(SystemExit):
        main(("worktree", "add", "demo"))
    (tmp_path / "repo--demo" / "notes.md").write_text("draft", encoding="utf8")

    with raises(SystemExit) as exc_info:
        main(("worktree", "remove", "demo"))

    assert exc_info.value.code == 1
    assert (tmp_path / "repo--demo" / "notes.md").is_file()
