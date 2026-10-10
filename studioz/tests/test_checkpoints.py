import subprocess
from pathlib import Path

from pytest import raises
from studioz.checkpoints import (
    UndoRefusedError,
    forget,
    last,
    record,
    snapshot,
    undo,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")


def test_undo_puts_back_what_the_turn_changed(workspace: Path, tmp_path: Path) -> None:
    state = tmp_path / "state"
    index = state / "index"
    deck = workspace / "client" / "abc" / "deck.yml"
    _write(workspace / "notes.md", "à moi\n")  # untracked, there before
    before = snapshot(workspace, index)
    assert before is not None

    _write(deck, "name: changed\n")
    _write(workspace / "content" / "new.md", "nouveau\n")
    (workspace / "notes.md").unlink()
    (workspace / ".run").mkdir(exist_ok=True)
    _write(workspace / ".run" / "ignored", "x")  # ignored: never in a turn
    after = snapshot(workspace, index)
    assert after is not None
    turn = record(workspace, state, before, after)

    assert turn is not None
    assert turn.files == ("client/abc/deck.yml", "content/new.md", "notes.md")
    assert last(state) == turn
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=workspace, capture_output=True, text=True
    ).stdout
    assert "A " not in status  # the workspace's own index never moved

    undone = undo(workspace, index, turn)

    assert undone.restored == turn.files
    assert undone.kept == ()
    assert deck.read_text(encoding="utf8") == "name: abc\n"
    assert not (workspace / "content" / "new.md").exists()
    assert (workspace / "notes.md").read_text(encoding="utf8") == "à moi\n"
    forget(workspace, state)
    assert last(state) is None


def test_a_file_changed_since_is_left_alone(workspace: Path, tmp_path: Path) -> None:
    index = tmp_path / "index"
    deck = workspace / "client" / "abc" / "deck.yml"
    before = snapshot(workspace, index)
    _write(deck, "name: by the agent\n")
    _write(workspace / "a.md", "by the agent\n")
    turn = record(workspace, tmp_path, before or "", snapshot(workspace, index) or "")
    assert turn is not None
    _write(deck, "name: then by the person\n")

    undone = undo(workspace, index, turn)

    assert undone.restored == ("a.md",)
    assert undone.kept == ("client/abc/deck.yml",)
    assert deck.read_text(encoding="utf8") == "name: then by the person\n"


def test_no_undo_after_a_commit(workspace: Path, tmp_path: Path) -> None:
    index = tmp_path / "index"
    before = snapshot(workspace, index)
    _write(workspace / "a.md", "x\n")
    turn = record(workspace, tmp_path, before or "", snapshot(workspace, index) or "")
    assert turn is not None
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@e.com"]
    subprocess.run([*git, "add", "a.md"], cwd=workspace, check=True)
    subprocess.run([*git, "commit", "-qm", "a"], cwd=workspace, check=True)

    with raises(UndoRefusedError, match="Vous avez committé"):
        undo(workspace, index, turn)
    assert (workspace / "a.md").exists()


def test_a_turn_without_changes_is_not_kept(workspace: Path, tmp_path: Path) -> None:
    tree = snapshot(workspace, tmp_path / "index")
    assert tree is not None
    assert record(workspace, tmp_path, tree, tree) is None
    assert snapshot(tmp_path / "not-git", tmp_path / "other-index") is None
