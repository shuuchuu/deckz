import json
import subprocess
from pathlib import Path

from deckz.agent_hooks import (
    bash_denial,
    commands,
    post_edit_report,
    session_start,
    stop_report,
)
from deckz.configuring.settings import ChecksSettings, GlobalPaths, GlobalSettings


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(cwd),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _init(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--quiet", "-b", "main", str(tmp_path))
    return tmp_path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")


def _commit(repo: Path, subject: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", subject)


_DEFAULT_PANDOC = ("pandoc", "-f", "markdown", "-t", "typst")


def _settings(
    git_dir: Path, *, pandoc_command: tuple[str, ...] = _DEFAULT_PANDOC
) -> GlobalSettings:
    return GlobalSettings(
        pandoc_command=pandoc_command,
        paths=GlobalPaths(current_dir=git_dir, git_dir=git_dir),
    )


def _bash_payload(command: str, cwd: Path) -> dict:
    return {"tool_input": {"command": command}, "cwd": str(cwd)}


# -- commands() ---------------------------------------------------------


def test_commands_splits_on_separators() -> None:
    assert commands("echo a && echo b; echo c") == [
        ["echo", "a"],
        ["echo", "b"],
        ["echo", "c"],
    ]


def test_commands_drops_heredoc_bodies() -> None:
    script = "git commit -F- <<EOF\nFix: discard everything\nEOF"
    assert commands(script) == [["git", "commit", "-F-"]]


# -- bash_denial: generic built-ins --------------------------------------


def test_bash_denial_denies_add_all(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    settings = _settings(repo)

    reason = bash_denial(settings, _bash_payload("git add -A", repo))

    assert reason is not None
    assert "Stage explicit paths" in reason


def test_bash_denial_allows_add_explicit_path(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "a.md", "hello")
    settings = _settings(repo)

    assert bash_denial(settings, _bash_payload("git add a.md", repo)) is None


def test_bash_denial_denies_commit_dash_a(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    settings = _settings(repo)

    reason = bash_denial(settings, _bash_payload("git commit -am x", repo))

    assert reason is not None
    assert "commit -a" in reason


def test_bash_denial_denies_skipping_the_hooks(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    settings = _settings(repo)

    for command in (
        "git commit --no-verify -m x",
        "git commit -nm x",
        "git commit -n",
        "git push --no-verify",
        "git -c core.hooksPath=/dev/null commit -m x",
    ):
        reason = bash_denial(settings, _bash_payload(command, repo))
        assert reason is not None, command
        assert "Never skip the git hooks" in reason


def test_bash_denial_allows_an_n_inside_an_option_value(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    settings = _settings(repo)

    for command in ("git commit -mnew", "git push -n origin main"):
        assert bash_denial(settings, _bash_payload(command, repo)) is None, command


def test_bash_denial_denies_clean_without_dry_run(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    settings = _settings(repo)

    reason = bash_denial(settings, _bash_payload("git clean -fd", repo))

    assert reason is not None
    assert "git clean" in reason


def test_bash_denial_allows_clean_dry_run(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    settings = _settings(repo)

    assert bash_denial(settings, _bash_payload("git clean -n", repo)) is None


def test_bash_denial_denies_checkout_discarding_changes(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "a.md", "v1")
    _commit(repo, "Add a")
    _write(repo / "a.md", "v2")
    settings = _settings(repo)

    reason = bash_denial(settings, _bash_payload("git checkout -- a.md", repo))

    assert reason is not None
    assert "a.md" in reason


def test_bash_denial_allows_checkout_of_a_clean_file(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "a.md", "v1")
    _commit(repo, "Add a")
    settings = _settings(repo)

    assert bash_denial(settings, _bash_payload("git checkout -- a.md", repo)) is None


def test_bash_denial_denies_reset_hard_with_dirty_tree(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "a.md", "v1")
    _commit(repo, "Add a")
    _write(repo / "a.md", "v2")
    settings = _settings(repo)

    reason = bash_denial(settings, _bash_payload("git reset --hard", repo))

    assert reason is not None
    assert "discard" in reason


def test_bash_denial_allows_plain_commands(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    settings = _settings(repo)

    assert bash_denial(settings, _bash_payload("echo hello", repo)) is None
    assert bash_denial(settings, _bash_payload("git status", repo)) is None
    assert bash_denial(settings, _bash_payload("git commit -m x", repo)) is None


def test_bash_denial_uses_the_repo_plugin(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    hooks_module = repo / "templates" / "hooks.py"
    hooks_module.parent.mkdir(parents=True)
    hooks_module.write_text(
        "def deny_bash(words, cwd, settings):\n"
        "    if 'push' in words and 'videos' in words:\n"
        "        return 'never push to videos'\n"
        "    return None\n",
        encoding="utf8",
    )
    settings = _settings(repo)

    reason = bash_denial(settings, _bash_payload("git push videos main", repo))

    assert reason == "never push to videos"
    assert bash_denial(settings, _bash_payload("git push origin main", repo)) is None


# -- post_edit_report -----------------------------------------------------


def test_post_edit_report_is_silent_on_a_clean_file(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    path = repo / "content" / "topic" / "topic.md"
    _write(path, "# Topic\n\nHello.\n")
    settings = _settings(repo)

    report = post_edit_report(settings, {"tool_input": {"file_path": str(path)}})

    assert report is None


def test_post_edit_report_ignores_a_non_content_extension(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    path = repo / "content" / "topic" / "notes.tex"
    _write(path, r"\section{x}")
    settings = _settings(repo)

    report = post_edit_report(settings, {"tool_input": {"file_path": str(path)}})

    assert report is None


def test_post_edit_report_flags_a_pandoc_failure(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    path = repo / "content" / "topic" / "topic.md"
    _write(path, "# Topic\n\nHello.\n")
    settings = _settings(
        repo, pandoc_command=("pandoc", "--this-flag-does-not-exist", "-t", "typst")
    )

    report = post_edit_report(settings, {"tool_input": {"file_path": str(path)}})

    assert report is not None
    assert "pandoc" in report
    # The scratch conversion target is cleaned up either way.
    assert not any(path.parent.glob(".topic.md.deckz-hook-check*"))


def test_post_edit_report_flags_a_content_check_problem(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    path = repo / "content" / "topic" / "topic.md"
    _write(path, "before\n\n```{=latex}\nraw\n```\n")
    settings = _settings(repo)

    report = post_edit_report(settings, {"tool_input": {"file_path": str(path)}})

    assert report is not None
    assert "raw-latex" in report
    assert "{=latex}" in report


def test_post_edit_report_skips_opt_in_checks(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    path = repo / "content" / "topic" / "topic.md"
    _write(path, "before\n\n```{=latex}\nraw\n```\n")
    settings = _settings(repo).model_copy(
        update={"checks": ChecksSettings(opt_in=("raw-latex",))}
    )

    report = post_edit_report(settings, {"tool_input": {"file_path": str(path)}})

    assert report is None


# -- session_start / stop_report ------------------------------------------


def _pair(repo: Path) -> tuple[Path, Path]:
    fr = repo / "content" / "topic" / "topic.md"
    en = repo / "content" / "topic" / "en" / "topic.md"
    return fr, en


def test_stop_report_is_silent_on_the_first_call(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    fr, en = _pair(repo)
    _write(fr, "fr v1")
    _write(en, "en v1")
    _commit(repo, "Add topic")
    settings = _settings(repo)

    assert stop_report(settings, {"session_id": "s1"}) is None


def test_stop_report_flags_a_one_sided_change(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    fr, en = _pair(repo)
    _write(fr, "fr v1")
    _write(en, "en v1")
    _commit(repo, "Add topic")
    settings = _settings(repo)
    session_start(settings, {"session_id": "s1"})

    _write(fr, "fr v2")

    report = stop_report(settings, {"session_id": "s1"})

    assert report is not None
    assert "topic/topic.md" in report
    assert "didn't" in report


def test_stop_report_is_silent_when_both_sides_change(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    fr, en = _pair(repo)
    _write(fr, "fr v1")
    _write(en, "en v1")
    _commit(repo, "Add topic")
    settings = _settings(repo)
    session_start(settings, {"session_id": "s1"})

    _write(fr, "fr v2")
    _write(en, "en v2")

    assert stop_report(settings, {"session_id": "s1"}) is None


def test_stop_report_does_not_repeat_the_same_finding(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    fr, en = _pair(repo)
    _write(fr, "fr v1")
    _write(en, "en v1")
    _commit(repo, "Add topic")
    settings = _settings(repo)
    session_start(settings, {"session_id": "s1"})
    _write(fr, "fr v2")
    first = stop_report(settings, {"session_id": "s1"})
    assert first is not None

    second = stop_report(settings, {"session_id": "s1"})

    assert second is None


def test_stop_report_respects_stop_hook_active(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    fr, en = _pair(repo)
    _write(fr, "fr v1")
    _write(en, "en v1")
    _commit(repo, "Add topic")
    settings = _settings(repo)
    session_start(settings, {"session_id": "s1"})
    _write(fr, "fr v2")

    report = stop_report(settings, {"session_id": "s1", "stop_hook_active": True})

    assert report is None


def test_session_start_keeps_an_existing_snapshot(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    fr, en = _pair(repo)
    _write(fr, "fr v1")
    _write(en, "en v1")
    _commit(repo, "Add topic")
    settings = _settings(repo)
    session_start(settings, {"session_id": "s1"})
    state_file = repo / ".check" / "hooks-sessions" / "s1.json"
    before = json.loads(state_file.read_text(encoding="utf8"))

    _write(fr, "fr v2")  # Changes after the snapshot shouldn't alter it.
    session_start(settings, {"session_id": "s1"})

    after = json.loads(state_file.read_text(encoding="utf8"))
    assert after == before
