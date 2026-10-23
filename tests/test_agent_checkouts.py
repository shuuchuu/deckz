import subprocess
from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

from deckz.agent_checkouts import create_worktree, edit_denial, remove_worktree
from deckz.agent_hooks import bash_denial, commands, post_bash_report
from deckz.configuring.settings import GlobalPaths, GlobalSettings, WorktreeSettings


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@e.com", *args],
        check=True,
        capture_output=True,
    )


def _checkouts(tmp_path: Path) -> tuple[Path, Path]:
    """A repository's main checkout and a worktree of it, next to each other.

    Returns:
        Both roots.
    """
    main = tmp_path / "repo"
    _git(tmp_path, "init", "--quiet", "-b", "main", str(main))
    (main / "a.md").write_text("a\n", encoding="utf8")
    _git(main, "add", "a.md")
    _git(main, "commit", "-m", "Add a")
    worktree = tmp_path / "repo--x"
    _git(main, "worktree", "add", "--quiet", "-b", "ws/x", str(worktree))
    return main, worktree


def _settings(git_dir: Path, *, required: bool = True) -> GlobalSettings:
    return GlobalSettings(
        paths=GlobalPaths(current_dir=git_dir, git_dir=git_dir),
        worktree=WorktreeSettings(required_for_agents=required),
    )


def _edit(target: Path, cwd: Path) -> dict:
    return {"tool_input": {"file_path": str(target)}, "cwd": str(cwd)}


def _bash(command: str, cwd: Path) -> dict:
    return {"tool_input": {"command": command}, "cwd": str(cwd)}


# -- commands() ---------------------------------------------------------


def test_commands_drops_file_descriptor_duplications() -> None:
    assert commands("make 2>&1 | tail -3") == [["make"], ["tail", "-3"]]
    assert commands("make &> log") == [["make", ">", "log"]]


# -- edit_denial ---------------------------------------------------------


def test_edit_denial_denies_a_main_checkout_file(tmp_path: Path) -> None:
    main, _ = _checkouts(tmp_path)

    reason = edit_denial(_settings(main), _edit(main / "a.md", main))

    assert reason is not None
    assert "deckz worktree add" in reason


def test_edit_denial_denies_a_notebook_of_the_main_checkout(tmp_path: Path) -> None:
    main, _ = _checkouts(tmp_path)
    payload = {"tool_input": {"notebook_path": "lab.ipynb"}, "cwd": str(main)}

    assert edit_denial(_settings(main), payload) is not None


def test_edit_denial_allows_a_worktree_file_from_the_worktree(tmp_path: Path) -> None:
    _, worktree = _checkouts(tmp_path)

    assert edit_denial(_settings(worktree), _edit(worktree / "a.md", worktree)) is None


def test_edit_denial_wants_the_session_in_the_worktree(tmp_path: Path) -> None:
    main, worktree = _checkouts(tmp_path)

    reason = edit_denial(_settings(main), _edit(worktree / "a.md", main))

    assert reason is not None
    assert "EnterWorktree" in reason


def test_edit_denial_allows_a_file_outside_the_repository(tmp_path: Path) -> None:
    main, _ = _checkouts(tmp_path)

    assert edit_denial(_settings(main), _edit(tmp_path / "notes.md", main)) is None


def test_edit_denial_is_off_by_default(tmp_path: Path) -> None:
    main, _ = _checkouts(tmp_path)
    settings = _settings(main, required=False)

    assert edit_denial(settings, _edit(main / "a.md", main)) is None


# -- main_checkout_denial, through bash_denial ---------------------------


def test_bash_denial_allows_reading_the_main_checkout(tmp_path: Path) -> None:
    main, _ = _checkouts(tmp_path)
    settings = _settings(main)

    for command in (
        "ls; git status && git log --oneline | head -3",
        "cat a.md 2>&1 | grep x > /dev/null",
        "find . -name '*.md'",
        "sed -n 1,5p a.md",
        "git diff HEAD~1 -- a.md",
        "git branch --list",
        "git merge --ff-only ws/x",
        "deckz show paths --workdir decks/x",
        "deckz show paths --lang=en --quiet",
        "uv run --quiet deckz status",
        "deckz i18n stale",
        "deckz worktree add y",
        "git -C ../repo--x commit -m x",
        "cd ../repo--x && python3 script.py > out.txt",
        "python3 script.py",  # Watched instead: see post_bash_report.
        "uv run python tools/report.py --out /tmp/report.txt",
        "sed -i s/a/b/ /tmp/notes.md",
        "cp a.md /tmp/a.md",
        "tar -czf /tmp/a.tgz a.md",
    ):
        assert bash_denial(settings, _bash(command, main)) is None, command


def test_bash_denial_denies_changing_the_main_checkout(tmp_path: Path) -> None:
    main, _ = _checkouts(tmp_path)
    settings = _settings(main)

    for command in (
        "git commit -m x",
        "git add a.md",
        "git checkout -b other",
        "git merge ws/x",
        "uv sync",
        "pip install requests",
        "npm install",
        "sed -i s/a/b/ a.md",
        "perl -pi -e s/a/b/ a.md",
        "cp /tmp/a.md a.md",
        "tar -xzf /tmp/a.tgz",
        "echo x > a.md",
        "echo x >> a.md",
        "find . -name '*.pyc' -delete",
        "sort -o a.md a.md",
        "deckz run --workdir decks/x",
        "deckz labs fmt",
        "rm a.md",
        "cd ../repo--x && cd ../repo && touch b.md",
    ):
        reason = bash_denial(settings, _bash(command, main))
        assert reason is not None, command
        assert "deckz worktree add" in reason, command


def test_bash_denial_denies_writing_the_main_checkout_from_a_worktree(
    tmp_path: Path,
) -> None:
    _, worktree = _checkouts(tmp_path)
    settings = _settings(worktree)

    for command in (
        "cp a.md ../repo/a.md",
        "echo x > ../repo/a.md",
        "git -C ../repo add a.md",
    ):
        assert bash_denial(settings, _bash(command, worktree)) is not None, command
    for command in (
        "python3 script.py",
        "cat ../repo/a.md",
        "git commit -m x",
        "deckz run --workdir decks/x --no-print",
    ):
        assert bash_denial(settings, _bash(command, worktree)) is None, command


def test_bash_denial_leaves_the_main_checkout_alone_by_default(tmp_path: Path) -> None:
    main, _ = _checkouts(tmp_path)
    settings = _settings(main, required=False)

    assert bash_denial(settings, _bash("python3 script.py > a.md", main)) is None


# -- the snapshot around a command in the main checkout --------------------


def _run(settings: GlobalSettings, command: str, cwd: Path, **extra: str) -> dict:
    """Run `command` the way Claude Code would, between the Bash hooks.

    Returns:
        The PostToolUse payload, for `post_bash_report`.
    """
    payload = {"session_id": "s1", "tool_use_id": "t1", **_bash(command, cwd), **extra}
    assert bash_denial(settings, payload) is None
    subprocess.run(command, shell=True, cwd=cwd, check=False)
    return payload


def test_post_bash_report_flags_what_a_command_changed(tmp_path: Path) -> None:
    main, _ = _checkouts(tmp_path)
    settings = _settings(main)
    (main / "b.md").write_text("user's\n", encoding="utf8")  # The user's own edit.

    payload = _run(settings, "python3 -c \"open('a.md', 'w').write('x')\"", main)
    report = post_bash_report(settings, payload)

    assert report is not None
    assert "- a.md" in report
    assert "b.md" not in report
    assert not list((main / ".git" / "deckz-bash-snapshots").iterdir())


def test_post_bash_report_is_silent_on_a_command_writing_elsewhere(
    tmp_path: Path,
) -> None:
    main, _ = _checkouts(tmp_path)
    settings = _settings(main)
    out = tmp_path / "out.txt"

    payload = _run(settings, f"python3 -c \"open('{out}', 'w').write('x')\"", main)

    assert post_bash_report(settings, payload) is None
    assert out.is_file()


def test_a_session_may_restore_what_it_changed_only(tmp_path: Path) -> None:
    main, _ = _checkouts(tmp_path)
    settings = _settings(main)
    (main / "b.md").write_text("user's\n", encoding="utf8")
    payload = _run(
        settings,
        "python3 -c \"open('a.md', 'w').write('x'); open('c.md', 'w').write('x')\"",
        main,
    )
    assert post_bash_report(settings, payload) is not None

    user = {"session_id": "s1", **_bash("git restore b.md", main)}
    assert bash_denial(settings, user) is not None
    restore = _run(settings, "git restore -- a.md && rm c.md", main, tool_use_id="t2")

    assert post_bash_report(settings, restore) is None
    assert (main / "a.md").read_text(encoding="utf8") == "a\n"
    assert not (main / "c.md").exists()
    # Back to HEAD: no longer the session's to discard.
    (main / "a.md").write_text("user's\n", encoding="utf8")
    later = {"session_id": "s1", **_bash("git restore a.md", main)}
    assert bash_denial(settings, later) is not None


# -- WorktreeCreate / WorktreeRemove --------------------------------------


def test_create_worktree_makes_a_deckz_worktree(tmp_path: Path) -> None:
    main, _ = _checkouts(tmp_path)

    path = create_worktree(_settings(main, required=False), "feature/x.y")

    assert path == tmp_path / "repo--feature-x-y"
    assert (path / "a.md").is_file()
    removed = remove_worktree(_settings(main), path)
    assert not path.exists()
    assert not removed.kept_branch


def test_worktree_remove_hook_reports_the_builds_handed_over(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    from io import StringIO
    from json import dumps

    from deckz.cli import main as deckz
    from deckz.stamps import write_stamp

    main = tmp_path / "repo"
    _git(tmp_path, "init", "--quiet", "-b", "main", str(main))
    (main / ".gitignore").write_text("/built/\n", encoding="utf8")
    (main / "deckz.yml").write_text("worktree:\n  seed: [built]\n", encoding="utf8")
    _git(main, "add", ".gitignore", "deckz.yml")
    _git(main, "commit", "-m", "Init")
    worktree = tmp_path / "repo--x"
    _git(main, "worktree", "add", "--quiet", "-b", "ws/x", str(worktree))
    (worktree / "built").mkdir()
    write_stamp(worktree / "built" / "fig.svg", "s")
    (worktree / "built" / "fig.svg").write_text("<svg/>", encoding="utf8")
    payload = dumps({"worktree_path": str(worktree)})
    monkeypatch.setattr("sys.stdin", StringIO(payload))

    deckz(("hooks", "worktree-remove", "--workdir", str(main)))

    captured = capsys.readouterr()
    assert not worktree.exists()
    assert (main / "built" / "fig.svg").read_text(encoding="utf8") == "<svg/>"
    assert "copied 1 build(s) into the main checkout, set aside 0" in captured.err
    assert captured.out == ""
