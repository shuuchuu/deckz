import json
import shlex
from pathlib import Path

from pygit2 import init_repository
from pytest import raises

from deckz.exceptions import HookInstallRefusedError
from deckz.hooks_install import (
    deckz_command,
    hooks_dir,
    install_claude_hooks,
    install_hooks,
)


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
        "PostToolUseFailure",
        "SessionStart",
        "Stop",
        "WorktreeCreate",
        "WorktreeRemove",
    }
    post_bash = settings["hooks"]["PostToolUseFailure"][0]["hooks"][0]["command"]
    assert post_bash.endswith(deckz_command("hooks post-bash"))
    assert post_bash.startswith("[ -n ")  # Skipped unless pre-bash left a snapshot.
    pre_bash = settings["hooks"]["PreToolUse"][0]
    assert pre_bash["matcher"] == "Bash"
    assert pre_bash["hooks"][0]["command"] == deckz_command("hooks pre-bash")


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
    assert commands == {
        "my-own-hook",
        deckz_command("hooks pre-bash"),
        deckz_command("hooks pre-edit"),
    }


def test_install_hooks_writes_into_core_hooks_path(tmp_path: Path) -> None:
    repository = init_repository(str(tmp_path))
    repository.config["core.hooksPath"] = ".githooks"

    written = install_hooks(tmp_path)

    assert hooks_dir(tmp_path) == tmp_path / ".githooks"
    assert {path.parent for path in written} == {tmp_path / ".githooks"}


def test_hooks_dir_of_a_linked_worktree_is_the_main_checkouts(tmp_path: Path) -> None:
    # A linked worktree's `.git` is a file: git runs the shared hooks.
    import subprocess

    main = tmp_path / "main"
    subprocess.run(["git", "init", "-q", "-b", "main", str(main)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(main),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@e.com",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "Initial",
        ],
        check=True,
    )
    worktree = tmp_path / "worktree"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", str(worktree)], check=True
    )

    assert hooks_dir(worktree) == (main / ".git" / "hooks").resolve()
    assert install_hooks(worktree)[0].parent == (main / ".git" / "hooks").resolve()


def test_hooks_fall_back_to_uv_when_deckz_is_not_on_the_path(tmp_path: Path) -> None:
    init_repository(str(tmp_path))

    written = install_hooks(tmp_path)

    for path in written:
        body = path.read_text(encoding="utf-8")
        assert "command -v deckz" in body
        assert "uv run --quiet deckz" in body


def test_install_claude_hooks_updates_an_older_deckz_command(tmp_path: Path) -> None:
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {"hooks": [{"type": "command", "command": "deckz hooks stop"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    install_claude_hooks(tmp_path)

    settings = json.loads(path.read_text(encoding="utf-8"))
    # The current command, and the current timeout.
    assert settings["hooks"]["Stop"] == [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": deckz_command("hooks stop"),
                    "timeout": 60,
                }
            ]
        }
    ]


def test_install_claude_hooks_updates_an_older_matcher(tmp_path: Path) -> None:
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    group = {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [{"type": "command", "command": "deckz hooks post-edit"}],
    }
    path.write_text(json.dumps({"hooks": {"PostToolUse": [group]}}), encoding="utf-8")

    install_claude_hooks(tmp_path)

    settings = json.loads(path.read_text(encoding="utf-8"))
    updated = settings["hooks"]["PostToolUse"][0]
    assert updated["matcher"] == "Edit|Write|MultiEdit|NotebookEdit"


def test_install_ci_workflow_writes_a_valid_workflow(tmp_path: Path) -> None:
    import yaml

    from deckz.configuring.settings import CiSettings
    from deckz.hooks_install import install_ci_workflow

    ci = CiSettings(
        deckz_repository="owner/deckz",
        apt_packages=("build-essential", "pkg-config"),
        nightly_checks=("missing-en",),
    )
    path = install_ci_workflow(tmp_path, ci)

    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    # The container's apt packages bring in a Python without its headers.
    assert workflow["jobs"]["check"]["env"]["UV_PYTHON_PREFERENCE"] == "only-managed"
    steps = workflow["jobs"]["check"]["steps"]
    assert any(
        step.get("with", {}).get("repository") == "owner/deckz" for step in steps
    )
    runs = [step.get("run", "") for step in steps]
    assert "uv run deckz check --plain" in runs
    assert "uv run deckz check --plain missing-en" in runs
    assert any("deckz hooks check-commits" in run for run in runs)
    # A plain scalar would fold the line continuation into `\ `, which makes
    # the next package's name start with a space.
    apt = next(run for run in runs if "apt-get install" in run)
    assert shlex.split(apt)[-2:] == ["build-essential", "pkg-config"]
    # The container's root can only run git on the runner's checkouts once
    # they're trusted, and `deckz check` runs git.
    trust = next(i for i, run in enumerate(runs) if "safe.directory" in run)
    assert trust < runs.index("uv run deckz check --plain")
    # Ours: overwritten without --force.
    install_ci_workflow(tmp_path, ci)


def test_ci_workflow_builds_the_decks_changed_overnight() -> None:
    import yaml

    from deckz.configuring.settings import CiSettings
    from deckz.hooks_install import ci_workflow

    def runs(ci: CiSettings) -> list[str]:
        steps = yaml.safe_load(ci_workflow(ci))["jobs"]["check"]["steps"]
        return [step.get("run", "") for step in steps]

    assert not any("run decks" in run for run in runs(CiSettings()))
    found = runs(
        CiSettings(nightly_builds=("fr", "en"), videos_repository="owner/videos")
    )
    fetch = found.index(
        "uv run deckz videos fetch --source https://github.com/owner/videos"
    )
    build = next(i for i, run in enumerate(found) if "deckz run decks" in run)
    assert fetch < build
    assert "--lang fr en" in found[build]
    assert '${BASE:+--since "$BASE"}' in found[build]
    # No videos repository: no fetch.
    assert not any(
        "videos fetch" in run for run in runs(CiSettings(nightly_builds=("fr",)))
    )

    ci = CiSettings(nightly_builds=("fr",), user_variables={"trainer_name": "CI"})
    found = runs(ci)
    write = next(i for i, run in enumerate(found) if "variables.yml" in run)
    assert "trainer_name: CI\n" in found[write]
    assert write < next(i for i, run in enumerate(found) if "run decks" in run)

    ci = CiSettings(nightly_builds=("fr",), cache_paths=("assets/plt", "assets/svg"))
    steps = yaml.safe_load(ci_workflow(ci))["jobs"]["check"]["steps"]
    (cache,) = [s for s in steps if s.get("uses", "").startswith("actions/cache")]
    # Relative to the workspace, not to the job's working directory.
    assert cache["with"]["path"].splitlines() == [
        "${{ github.event.repository.name }}/assets/plt",
        "${{ github.event.repository.name }}/assets/svg",
    ]
    assert cache["with"]["restore-keys"] == "deckz-nightly-"


def test_install_ci_workflow_refuses_a_foreign_workflow(tmp_path: Path) -> None:
    from deckz.configuring.settings import CiSettings
    from deckz.hooks_install import install_ci_workflow

    path = tmp_path / ".github" / "workflows" / "deckz.yml"
    path.parent.mkdir(parents=True)
    path.write_text("name: mine\n", encoding="utf-8")

    with raises(HookInstallRefusedError):
        install_ci_workflow(tmp_path, CiSettings())
