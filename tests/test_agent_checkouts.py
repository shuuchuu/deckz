import subprocess
from pathlib import Path

from deckz.agent_checkouts import edit_denial
from deckz.agent_hooks import bash_denial, commands
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
        "python3 script.py",
        "uv run python script.py",
        "sed -i s/a/b/ a.md",
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
