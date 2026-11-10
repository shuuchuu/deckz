import json
import shlex
from pathlib import Path
from typing import Any

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
        "WorktreeCreate",
        "WorktreeRemove",
    }
    post_bash = settings["hooks"]["PostToolUseFailure"][0]["hooks"][0]["command"]
    assert post_bash.endswith(deckz_command("hooks post-bash"))
    assert post_bash.startswith("[ -n ")  # Skipped unless pre-bash left a snapshot.
    pre_bash = settings["hooks"]["PreToolUse"][0]
    assert pre_bash["matcher"] == "Bash"
    assert pre_bash["hooks"][0]["command"].endswith(deckz_command("hooks pre-bash"))


def _hook(
    tmp_path: Path,
    event: str,
    subcommand: str,
    extensions: tuple[str, ...] = (".md",),
) -> str:
    path = install_claude_hooks(tmp_path, extensions)
    settings = json.loads(path.read_text(encoding="utf-8"))
    return next(
        hook["command"]
        for group in settings["hooks"][event]
        for hook in group["hooks"]
        if f"deckz hooks {subcommand}" in hook["command"]
    )


def _run_hook(command: str, payload: dict, cwd: Path, tmp_path: Path) -> str:
    """Run a hook's command with a `deckz` that says it ran.

    Returns:
        What it printed: nothing when the command's own test skipped deckz.
    """
    import os
    import subprocess

    fake = tmp_path / "bin" / "deckz"
    fake.parent.mkdir(exist_ok=True)
    fake.write_text('#!/bin/sh\ncat >/dev/null; echo "ran $*"\n', encoding="utf-8")
    fake.chmod(0o755)
    return subprocess.run(
        ["sh", "-c", command],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
        env={**os.environ, "PATH": f"{fake.parent}:{os.environ['PATH']}"},
    ).stdout.strip()


def _checkouts(tmp_path: Path) -> tuple[Path, Path]:
    import subprocess

    main, worktree = tmp_path / "repo", tmp_path / "repo--x"
    identity = ["-c", "user.name=t", "-c", "user.email=t@e.com"]
    for args in (
        ["init", "--quiet", "-b", "main", str(main)],
        ["-C", str(main), *identity, "commit", "--quiet", "--allow-empty", "-m", "x"],
        ["-C", str(main), "worktree", "add", "--quiet", "-b", "ws/x", str(worktree)],
    ):
        subprocess.run(["git", *args], check=True, capture_output=True)
    return main, worktree


def test_post_edit_hook_starts_deckz_for_a_content_file_only(tmp_path: Path) -> None:
    command = _hook(tmp_path, "PostToolUse", "post-edit")

    def ran(file: str) -> str:
        payload = {"tool_input": {"file_path": file, "new_string": 'a "b" $c'}}
        return _run_hook(command, payload, tmp_path, tmp_path)

    assert ran("/repo/content/a.md") == "ran hooks post-edit"
    assert ran("/repo/tools/a.py") == ""
    assert ran("/repo/labs/a.ipynb") == ""


def test_post_edit_hook_follows_the_content_extensions(tmp_path: Path) -> None:
    command = _hook(tmp_path, "PostToolUse", "post-edit", (".md", ".tex"))
    payload = {"tool_input": {"file_path": "/repo/content/a.tex"}}

    assert _run_hook(command, payload, tmp_path, tmp_path) == "ran hooks post-edit"


def test_pre_edit_hook_starts_deckz_for_the_main_checkout_only(tmp_path: Path) -> None:
    main, worktree = _checkouts(tmp_path)
    command = _hook(tmp_path, "PreToolUse", "pre-edit")

    def ran(file: Path, cwd: Path) -> str:
        payload = {"cwd": str(cwd), "tool_input": {"file_path": str(file)}}
        return _run_hook(command, payload, cwd, tmp_path)

    assert ran(worktree / "a.md", worktree) == ""
    assert ran(tmp_path / "notes.md", worktree) == ""
    assert ran(main / "a.md", worktree) == "ran hooks pre-edit"
    assert ran(worktree / "a.md", main) == "ran hooks pre-edit"


def test_pre_bash_hook_starts_deckz_for_what_it_can_deny(tmp_path: Path) -> None:
    main, worktree = _checkouts(tmp_path)
    command = _hook(tmp_path, "PreToolUse", "pre-bash")

    def ran(script: str, cwd: Path) -> str:
        payload = {"cwd": str(cwd), "tool_input": {"command": script}}
        return _run_hook(command, payload, cwd, tmp_path)

    for script in ("ls docs", "grep -n '>' a.md | head -3", f"cat {worktree}/a.md"):
        assert ran(script, worktree) == "", script
    for script in (
        "git add -A",
        "uv run deckz labs publish",
        "uv run doit publish-videos",
        f"cp a.md {main}/a.md",
        f"cd {main} && touch b.md",
        "touch ../repo/b.md",
        "touch ~/repo/b.md",
    ):
        assert ran(script, worktree) == "ran hooks pre-bash", script
    assert ran("ls docs", main) == "ran hooks pre-bash"


def test_install_claude_hooks_is_idempotent(tmp_path: Path) -> None:
    install_claude_hooks(tmp_path)

    path = install_claude_hooks(tmp_path)

    settings = json.loads(path.read_text(encoding="utf-8"))
    assert len(settings["hooks"]["SessionStart"]) == 1
    assert len(settings["hooks"]["PreToolUse"]) == 2


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
    assert "my-own-hook" in commands
    assert len(commands) == 3


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
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "deckz hooks session-start",
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    install_claude_hooks(tmp_path)

    settings = json.loads(path.read_text(encoding="utf-8"))
    # The current command, and the current timeout.
    assert settings["hooks"]["SessionStart"] == [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": deckz_command("hooks session-start"),
                    "timeout": 30,
                }
            ]
        }
    ]


def test_install_claude_hooks_removes_a_hook_deckz_no_longer_has(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    ours = {"type": "command", "command": deckz_command("hooks stop"), "timeout": 60}
    theirs = {"type": "command", "command": "my-own-hook"}
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [{"hooks": [ours]}],
                    "SubagentStop": [{"hooks": [dict(ours), theirs]}],
                }
            }
        ),
        encoding="utf-8",
    )

    install_claude_hooks(tmp_path)

    hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
    assert "Stop" not in hooks
    assert hooks["SubagentStop"] == [{"hooks": [theirs]}]


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


def test_ci_workflow_builds_the_decks_changed_in_the_week() -> None:
    import yaml

    from deckz.configuring.settings import CiSettings
    from deckz.hooks_install import ci_workflow

    def runs(ci: CiSettings) -> list[str]:
        steps = yaml.safe_load(ci_workflow(ci))["jobs"]["check"]["steps"]
        return [step.get("run", "") for step in steps]

    assert not any("run decks" in run for run in runs(CiSettings()))
    found = runs(CiSettings(builds=("fr", "en"), videos_repository="owner/videos"))
    fetch = found.index(
        "uv run deckz videos fetch --source https://github.com/owner/videos"
    )
    build = next(i for i, run in enumerate(found) if "deckz run decks" in run)
    assert fetch < build
    assert "--lang fr en" in found[build]
    assert '${BASE:+--since "$BASE"}' in found[build]
    assert '--before="7 days ago"' in found[build]  # Weekly by default.
    # No videos repository: no fetch.
    assert not any("videos fetch" in run for run in runs(CiSettings(builds=("fr",))))

    ci = CiSettings(builds=("fr",), user_variables={"trainer_name": "CI"})
    found = runs(ci)
    write = next(i for i, run in enumerate(found) if "variables.yml" in run)
    assert "trainer_name: CI\n" in found[write]
    assert write < next(i for i, run in enumerate(found) if "run decks" in run)

    ci = CiSettings(builds=("fr",), cache_paths=("assets/plt", "assets/svg"))
    steps = yaml.safe_load(ci_workflow(ci))["jobs"]["check"]["steps"]
    (cache,) = [s for s in steps if s.get("uses", "").startswith("actions/cache")]
    # Relative to the workspace, not to the job's working directory.
    assert cache["with"]["path"].splitlines() == [
        "${{ github.event.repository.name }}/assets/plt",
        "${{ github.event.repository.name }}/assets/svg",
    ]
    assert cache["with"]["restore-keys"] == "deckz-builds-"


def test_ci_workflow_runs_weekly_builds_apart_from_the_nightly_checks() -> None:
    import yaml

    from deckz.configuring.settings import CiSettings
    from deckz.hooks_install import ci_workflow

    def workflow(**kwargs: Any) -> dict[Any, Any]:
        return yaml.safe_load(ci_workflow(CiSettings(**kwargs)))

    weekly = workflow(nightly_checks=("missing-en",), builds=("fr",))
    # PyYAML reads `on` as True.
    assert [s["cron"] for s in weekly[True]["schedule"]] == ["0 3 * * *", "0 4 * * 0"]
    steps = {s["name"]: s for s in weekly["jobs"]["check"]["steps"]}
    assert "'0 3 * * *'" in steps["Nightly checks"]["if"]
    assert "'0 4 * * 0'" in steps["Build the decks changed in the last week"]["if"]
    nightly = workflow(builds=("fr",), builds_schedule="nightly")
    assert [s["cron"] for s in nightly[True]["schedule"]] == ["0 3 * * *"]
    steps = {s["name"]: s for s in nightly["jobs"]["check"]["steps"]}
    build = steps["Build the decks changed in the last day"]
    assert '--before="24 hours ago"' in build["run"]


def test_ci_workflow_reports_problems_in_an_issue_only_when_asked() -> None:
    import yaml

    from deckz.configuring.settings import CiSettings
    from deckz.hooks_install import ci_workflow

    def job(**kwargs: Any) -> dict[str, Any]:
        return yaml.safe_load(ci_workflow(CiSettings(**kwargs)))["jobs"]["check"]

    quiet = job(nightly_checks=("missing-en",), builds=("fr",))
    assert "permissions" not in quiet
    assert not any("ci-report" in s.get("run", "") for s in quiet["steps"])

    reporting = job(nightly_checks=("missing-en",), builds=("fr",), report_to=("me",))
    assert reporting["permissions"] == {"contents": "read", "issues": "write"}
    steps = {s["name"]: s for s in reporting["steps"]}
    report = steps["Report the problems in an issue"]
    assert report["if"].startswith("failure() && ")
    assert report["env"] == {"GITHUB_TOKEN": "${{ github.token }}"}
    assert report["run"] == "uv run deckz hooks ci-report ../deckz-reports"
    assert "../deckz-reports/checks.txt" not in steps["Nightly checks"]["run"]
    assert "mv checks.txt ../deckz-reports/" in steps["Nightly checks"]["run"]
    build = steps["Build the decks changed in the last week"]["run"]
    assert "--report ../deckz-reports/builds.md" in build


def test_ci_workflow_runs_the_labs_on_sundays_only_when_asked() -> None:
    import subprocess

    import yaml

    from deckz.configuring.settings import CiLabsSettings, CiSettings
    from deckz.hooks_install import ci_workflow

    # Without `labs`, nothing of it: regenerating the workflow changes nothing.
    for settings in (
        CiSettings(),
        CiSettings(nightly_checks=("missing-en",), report_to=("me",)),
    ):
        text = ci_workflow(settings)
        assert "labs" not in text
        assert "0 4 * * 0" not in text

    labs = CiLabsSettings(
        notebooks=("labs/notebooks/a", "labs/notebooks/b/demo-fr.ipynb"),
        requirements="labs/requirements.txt",
        packages=("lightning>=2",),
        index_urls=("https://download.pytorch.org/whl/cpu",),
        timeout=900,
    )
    quiet = yaml.safe_load(ci_workflow(CiSettings(labs=labs)))
    assert [s["cron"] for s in quiet[True]["schedule"]] == ["0 3 * * *", "0 4 * * 0"]
    steps = {s["name"]: s for s in quiet["jobs"]["check"]["steps"]}
    step = steps["Run the labs"]
    assert step["if"].startswith("(github.event.schedule == '0 4 * * 0' || ")
    assert step["if"].endswith(") && !cancelled()")
    assert step["run"].splitlines() == [
        "uv venv ../labs-venv --python 3.12",
        "uv pip install --python ../labs-venv/bin/python --index-strategy "
        "unsafe-best-match --extra-index-url https://download.pytorch.org/whl/cpu "
        "-r labs/requirements.txt 'lightning>=2'",
        "uv run deckz labs check --python ../labs-venv/bin/python --timeout 900 "
        "--smoke --deprecations labs/notebooks/a labs/notebooks/b/demo-fr.ipynb",
    ]
    assert "Report the problems in an issue" not in steps

    reporting = yaml.safe_load(ci_workflow(CiSettings(labs=labs, report_to=("me",))))
    steps = {s["name"]: s for s in reporting["jobs"]["check"]["steps"]}
    run = steps["Run the labs"]["run"]
    assert "> labs-install.txt 2>&1; then" in run
    assert "tail -n 60 labs-install.txt >> ../deckz-reports/labs.txt" in run
    assert "mv labs.txt ../deckz-reports/" in run
    assert "Report the problems in an issue" in steps
    # The step's script parses.
    subprocess.run(["sh", "-n"], input=run, text=True, check=True)


def test_ci_labs_installs_something() -> None:
    from pydantic import ValidationError

    from deckz.configuring.settings import CiLabsSettings

    with raises(ValidationError, match="installs nothing"):
        CiLabsSettings(notebooks=("labs/notebooks/a",))
    with raises(ValidationError):
        CiLabsSettings(notebooks=(), packages=("numpy",))


def test_install_ci_workflow_refuses_a_foreign_workflow(tmp_path: Path) -> None:
    from deckz.configuring.settings import CiSettings
    from deckz.hooks_install import install_ci_workflow

    path = tmp_path / ".github" / "workflows" / "deckz.yml"
    path.parent.mkdir(parents=True)
    path.write_text("name: mine\n", encoding="utf-8")

    with raises(HookInstallRefusedError):
        install_ci_workflow(tmp_path, CiSettings())
