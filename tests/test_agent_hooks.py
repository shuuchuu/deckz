import os
import subprocess
from pathlib import Path
from typing import Any

from deckz.agent_hooks import (
    bash_denial,
    commands,
    post_edit_report,
    session_start,
    stop_report,
)
from deckz.configuring.settings import (
    ChecksSettings,
    GlobalPaths,
    GlobalSettings,
    WorktreeSettings,
)


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


def test_post_edit_report_ignores_agent_notes(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    path = repo / "content" / "CLAUDE.md"
    _write(path, "# Notes\n\n```{=latex}\nraw\n```\n")
    settings = _settings(
        repo, pandoc_command=("pandoc", "--this-flag-does-not-exist", "-t", "typst")
    )

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


def test_post_edit_report_checks_only_the_edited_file(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    path = repo / "content" / "topic" / "topic.md"
    _write(path, "# Topic\n\nHello.\n")
    # Another file's problem, which a repo-wide run would find too.
    _write(repo / "content" / "other" / "other.md", _RAW_LATEX)
    settings = _settings(repo)

    report = post_edit_report(settings, {"tool_input": {"file_path": str(path)}})

    assert report is None


def test_post_edit_report_matches_a_problem_by_its_exact_path(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    path = repo / "content" / "topic.md"
    _write(path, "# Topic\n\nHello.\n")
    # Its path ends with the edited file's, which a substring match took for it.
    _write(repo / "content" / "deep" / "content" / "topic.md", _RAW_LATEX)
    settings = _settings(repo)

    report = post_edit_report(settings, {"tool_input": {"file_path": str(path)}})

    assert report is None


# -- session_start / stop_report ------------------------------------------

_RAW_LATEX = "# Topic\n\n```{=latex}\nraw\n```\n"


def _pair(repo: Path, name: str = "topic") -> tuple[Path, Path]:
    fr = repo / "content" / name / f"{name}.md"
    en = repo / "content" / name / "en" / f"{name}.md"
    return fr, en


def _both_sides_committed(repo: Path) -> tuple[GlobalSettings, Path, Path]:
    fr, en = _pair(repo)
    _write(fr, "# Topic\n")
    _write(en, "# Topic\n")
    _commit(repo, "Add topic")
    return _settings(repo), fr, en


def _edit(settings: GlobalSettings, path: Path, text: str) -> str | None:
    # An edit tool's write, and its PostToolUse hook.
    _write(path, text)
    payload = {"session_id": "s1", "tool_input": {"file_path": str(path)}}
    return post_edit_report(settings, payload)


def _worktree(tmp_path: Path) -> tuple[Path, Path]:
    """A repository with a topic pair committed, and a worktree of it.

    Returns:
        The main checkout and the worktree, next to each other.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _both_sides_committed(_init(repo))
    worktree = tmp_path / "repo--x"
    _git(repo, "worktree", "add", "--quiet", "-b", "ws/x", str(worktree))
    return repo, worktree


def _stop(settings: GlobalSettings, **payload: Any) -> str | None:
    return stop_report(settings, {"session_id": "s1", **payload})


def test_stop_report_flags_a_one_sided_edit(tmp_path: Path) -> None:
    settings, fr, _ = _both_sides_committed(_init(tmp_path))
    _edit(settings, fr, "# Topic\n\nUpdated.\n")

    report = _stop(settings)

    assert report is not None
    assert "content/topic/topic.md (not content/topic/en/topic.md)" in report


def test_stop_report_is_silent_when_both_sides_change(tmp_path: Path) -> None:
    settings, fr, en = _both_sides_committed(_init(tmp_path))
    _edit(settings, fr, "# Topic\n\nUpdated.\n")
    _edit(settings, en, "# Topic\n\nUpdated.\n")

    assert _stop(settings) is None


def test_stop_report_leaves_files_the_session_did_not_edit(tmp_path: Path) -> None:
    settings, fr, _ = _both_sides_committed(_init(tmp_path))
    # Another session's broken, one-sided edit of the same checkout.
    _write(fr, _RAW_LATEX)

    assert _stop(settings) is None


def test_stop_report_flags_a_one_sided_pair_once(tmp_path: Path) -> None:
    settings, fr, _ = _both_sides_committed(_init(tmp_path))
    _edit(settings, fr, "# Topic\n\nUpdated.\n")
    assert _stop(settings) is not None

    assert _stop(settings) is None
    _edit(settings, fr, "# Topic\n\nUpdated again.\n")
    assert _stop(settings) is None


def test_stop_report_respects_stop_hook_active(tmp_path: Path) -> None:
    settings, fr, _ = _both_sides_committed(_init(tmp_path))
    _edit(settings, fr, "# Topic\n\nUpdated.\n")

    assert _stop(settings, stop_hook_active=True) is None


def test_stop_report_lists_ten_paths_at_most(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    names = [f"topic{i:02}" for i in range(12)]
    for name in names:
        for path in _pair(repo, name):
            _write(path, "# Topic\n")
    _commit(repo, "Add topics")
    settings = _settings(repo)
    for name in names:
        _edit(settings, _pair(repo, name)[0], "# Topic\n\nUpdated.\n")

    report = _stop(settings)

    assert report is not None
    assert "topic09/topic09.md" in report
    assert "topic10/topic10.md" not in report
    assert "… and 2 more" in report


def test_stop_report_checks_a_worktree_file_written_without_the_edit_tool(
    tmp_path: Path,
) -> None:
    _, worktree = _worktree(tmp_path)
    settings = _settings(worktree)
    fr, en = _pair(worktree)
    # E.g. `cat >> file` from Bash: no PostToolUse hook saw it.
    _write(fr, _RAW_LATEX)
    _write(en, "# Topic\n\nUpdated.\n")

    report = _stop(settings)

    assert report is not None
    assert "content/topic/topic.md:\n  [raw-latex]" in report
    assert "content/topic/en/topic.md" not in report
    assert "one side only" not in report
    # Reported once, until the file changes again.
    assert _stop(settings) is None


def test_stop_report_flags_a_worktree_commit_changing_one_side(tmp_path: Path) -> None:
    _, worktree = _worktree(tmp_path)
    fr, _ = _pair(worktree)
    _write(fr, "# Topic\n\nUpdated.\n")
    _commit(worktree, "Update the French topic")

    report = _stop(_settings(worktree))

    assert report is not None
    assert "one side only in this worktree" in report


def test_stop_report_leaves_the_main_checkout_changes(tmp_path: Path) -> None:
    repo, worktree = _worktree(tmp_path)
    fr, _ = _pair(repo)
    _write(fr, _RAW_LATEX)  # Uncommitted in the main checkout,
    _commit(repo, "Break the French topic")  # then committed there.
    _write(fr, "# Topic\n\nAgain.\n")

    assert _stop(_settings(worktree)) is None


def test_stop_report_skips_what_post_edit_found_clean(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _, worktree = _worktree(tmp_path)
    settings = _settings(worktree)
    for path in _pair(worktree):
        assert _edit(settings, path, "# Topic\n\nUpdated.\n") is None

    def unexpected(*_: Any) -> None:
        msg = "checked again"
        raise AssertionError(msg)

    monkeypatch.setattr("deckz.agent_hooks._content_problems", unexpected)

    assert _stop(settings) is None


def test_stop_report_is_silent_in_a_main_checkout_agents_cannot_change(
    tmp_path: Path,
) -> None:
    settings, fr, _ = _both_sides_committed(_init(tmp_path))
    _edit(settings, fr, "# Topic\n\nUpdated.\n")
    settings = settings.model_copy(
        update={"worktree": WorktreeSettings(required_for_agents=True)}
    )

    assert _stop(settings) is None


def test_session_start_prunes_old_states(tmp_path: Path) -> None:
    settings, _, _ = _both_sides_committed(_init(tmp_path))
    states = tmp_path / ".check" / "hooks-sessions"
    _write(states / "old.json", "{}")
    _write(states / "recent.json", "{}")
    os.utime(states / "old.json", (0, 0))

    session_start(settings, {"session_id": "s1", "cwd": str(tmp_path)})

    assert sorted(path.name for path in states.iterdir()) == ["recent.json"]


def test_session_start_tells_a_main_checkout_session_the_rule(tmp_path: Path) -> None:
    repo, worktree = _worktree(tmp_path)
    rule = {"worktree": WorktreeSettings(required_for_agents=True)}
    settings = _settings(repo).model_copy(update=rule)

    context = session_start(settings, {"session_id": "s1", "cwd": str(repo)})

    assert context is not None
    assert "deckz worktree add" in context
    assert session_start(_settings(repo), {"cwd": str(repo)}) is None
    in_worktree = _settings(worktree).model_copy(update=rule)
    assert session_start(in_worktree, {"cwd": str(worktree)}) is None
