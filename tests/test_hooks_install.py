import json
from pathlib import Path

from pygit2 import init_repository
from pytest import raises

from deckz.exceptions import HookInstallRefusedError
from deckz.hooks_install import install_claude_hooks, install_hooks


def test_install_hooks_writes_both_hooks_executable(tmp_path: Path) -> None:
    init_repository(str(tmp_path))

    written = install_hooks(tmp_path)

    names = {path.name for path in written}
    assert names == {"pre-commit", "commit-msg"}
    for path in written:
        assert path.stat().st_mode & 0o111
        assert "deckz" in path.read_text(encoding="utf-8")


def test_install_hooks_refuses_to_overwrite_a_foreign_hook(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "pre-commit").write_text("#!/bin/sh\necho mine\n", encoding="utf-8")

    with raises(HookInstallRefusedError):
        install_hooks(tmp_path)


def test_install_hooks_force_overwrites_a_foreign_hook(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "pre-commit").write_text("#!/bin/sh\necho mine\n", encoding="utf-8")

    install_hooks(tmp_path, force=True)

    assert "deckz" in (hooks_dir / "pre-commit").read_text(encoding="utf-8")


def test_install_hooks_reinstalls_its_own_hook_without_force(tmp_path: Path) -> None:
    init_repository(str(tmp_path))

    install_hooks(tmp_path)
    install_hooks(tmp_path)  # Should not raise.


def test_install_claude_hooks_writes_every_event(tmp_path: Path) -> None:
    path = install_claude_hooks(tmp_path)

    settings = json.loads(path.read_text(encoding="utf-8"))
    assert set(settings["hooks"]) == {
        "PreToolUse",
        "PostToolUse",
        "SessionStart",
        "Stop",
    }
    pre_bash = settings["hooks"]["PreToolUse"][0]
    assert pre_bash["matcher"] == "Bash"
    assert pre_bash["hooks"][0]["command"] == "deckz hooks pre-bash"


def test_install_claude_hooks_is_idempotent(tmp_path: Path) -> None:
    install_claude_hooks(tmp_path)

    path = install_claude_hooks(tmp_path)

    settings = json.loads(path.read_text(encoding="utf-8"))
    assert len(settings["hooks"]["Stop"]) == 1


def test_install_claude_hooks_keeps_other_settings_and_hooks(tmp_path: Path) -> None:
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(ls:*)"]},
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "my-own-hook"}],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    install_claude_hooks(tmp_path)

    settings = json.loads(path.read_text(encoding="utf-8"))
    assert settings["permissions"] == {"allow": ["Bash(ls:*)"]}
    commands = {
        hook["command"]
        for group in settings["hooks"]["PreToolUse"]
        for hook in group["hooks"]
    }
    assert commands == {"my-own-hook", "deckz hooks pre-bash"}
