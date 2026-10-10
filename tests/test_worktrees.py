import os
import subprocess
from pathlib import Path

from pytest import raises

from deckz.configuring.settings import GlobalPaths, GlobalSettings, WorktreeSettings
from deckz.exceptions import WorktreeError
from deckz.worktrees import add, main_checkout, remove, worktrees


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(cwd),
            "-c",
            "user.name=test",
            "-c",
            "user.email=t@example.com",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")
    return path


def _make_repo(tmp_path: Path) -> Path:
    main = tmp_path / "repo"
    _git(tmp_path, "init", "-b", "main", str(main))
    _write(
        main / ".gitignore",
        "/assets/built/*.svg\n/assets/built/*.stamp\n/.env\n.venv/\n",
    )
    _write(main / "pyproject.toml", "[project]\n")
    _write(main / "uv.lock", "lock\n")
    _write(main / "assets" / "built" / "credits.yml", "author: Jane\n")
    _write(main / "figures" / "fig.typ", "Figure\n")
    _git(main, "add", "-A")
    _git(main, "commit", "-m", "Initial")
    # What git doesn't track: a build, the settings, the environment.
    _write(main / "assets" / "built" / "fig.svg", "<svg/>")
    _write(main / "assets" / "built" / "fig.svg.stamp", "abc\n")
    _write(main / ".env", "DECKZ_LANG=fr\n")
    _write(main / ".venv" / "bin" / "python", "")
    return main


def _settings(git_dir: Path) -> GlobalSettings:
    return GlobalSettings(
        paths=GlobalPaths(current_dir=git_dir, git_dir=git_dir),
        worktree=WorktreeSettings(seed=("assets/built",), link=(".env", ".venv")),
    )


def test_add_creates_the_worktree_next_to_the_main_checkout(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)

    added = add(_settings(main), "demo")

    assert added.path == tmp_path / "repo--demo"
    assert added.branch == "ws/demo"
    assert (added.path / "figures" / "fig.typ").is_file()
    assert _git(added.path, "branch", "--show-current").strip() == "ws/demo"
    assert main_checkout(added.path) == main


def test_add_copies_the_ignored_builds_with_their_times(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    svg = main / "assets" / "built" / "fig.svg"
    os.utime(svg, ns=(1_000_000_000, 1_000_000_000))
    # Another session's uncommitted edit of a tracked file stays in main.
    _write(main / "assets" / "built" / "credits.yml", "author: Someone else\n")

    added = add(_settings(main), "demo")

    copy = added.path / "assets" / "built" / "fig.svg"
    assert copy.read_text(encoding="utf8") == "<svg/>"
    assert copy.stat().st_mtime_ns == 1_000_000_000
    assert (added.path / "assets" / "built" / "fig.svg.stamp").is_file()
    assert added.copied == 2
    tracked = added.path / "assets" / "built" / "credits.yml"
    assert tracked.read_text(encoding="utf8") == "author: Jane\n"


def test_add_links_the_shared_files_and_keeps_them_ignored(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)

    added = add(_settings(main), "demo")

    assert added.linked == (".env", ".venv")
    assert (added.path / ".env").is_symlink()
    assert (added.path / ".venv").resolve() == (main / ".venv").resolve()
    # `.venv/` only matches a directory: the symlink must be excluded too.
    assert _git(added.path, "status", "--porcelain") == ""


def test_add_does_not_share_the_venv_when_dependencies_differ(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    _write(main / "uv.lock", "another lock\n")

    added = add(_settings(main), "demo")

    assert added.linked == (".env",)
    assert not (added.path / ".venv").exists()
    assert any(reason.startswith(".venv: ") for reason in added.not_linked)


def test_add_starts_from_base(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    first = _git(main, "rev-parse", "HEAD").strip()
    _write(main / "figures" / "other.typ", "Other\n")
    _git(main, "add", "figures/other.typ")
    _git(main, "commit", "-m", "Second")

    added = add(_settings(main), "demo", base="HEAD~1")

    assert added.base == first
    assert not (added.path / "figures" / "other.typ").exists()


def test_add_refuses_an_invalid_or_taken_name(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    add(_settings(main), "demo")

    with raises(WorktreeError, match="invalid"):
        add(_settings(main), "../escape")
    with raises(WorktreeError, match="already exists"):
        add(_settings(main), "demo")


def test_worktrees_lists_changes_and_unsynced_commits(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path
    _write(path / "figures" / "fig.typ", "Changed\n")
    _write(path / "figures" / "new.typ", "New\n")
    _git(path, "add", "figures/new.typ")
    _git(path, "commit", "-m", "New figure")

    (worktree,) = worktrees(_settings(main))

    assert worktree.name == "demo"
    assert worktree.path == path
    assert worktree.changes == (" M figures/fig.typ",)
    assert worktree.unsynced == 1


def test_remove_deletes_a_clean_worktree_and_its_branch(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path

    kept = remove(_settings(main), "demo")

    assert not kept
    assert not path.exists()
    assert _git(main, "branch", "--list", "ws/demo") == ""
    assert (main / ".env").is_file()
    assert (main / ".venv" / "bin" / "python").is_file()


def test_remove_refuses_uncommitted_changes(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path
    _write(path / "figures" / "fig.typ", "Changed\n")

    with raises(WorktreeError, match="uncommitted changes"):
        remove(_settings(main), "demo")
    assert path.is_dir()


def test_remove_refuses_unsynced_commits_and_keeps_them_when_forced(
    tmp_path: Path,
) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path
    _write(path / "figures" / "new.typ", "New\n")
    _git(path, "add", "figures/new.typ")
    _git(path, "commit", "-m", "New figure")

    with raises(WorktreeError, match="1 commit"):
        remove(_settings(main), "demo")
    kept = remove(_settings(main), "demo", force=True)

    assert kept
    assert not path.exists()
    assert _git(main, "branch", "--list", "ws/demo").strip() == "ws/demo"


def test_remove_counts_commits_merged_elsewhere_as_synced(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path
    _write(path / "figures" / "new.typ", "New\n")
    _git(path, "add", "figures/new.typ")
    _git(path, "commit", "-m", "New figure")
    _git(main, "merge", "--ff-only", "ws/demo")

    assert not remove(_settings(main), "demo")


def test_remove_refuses_an_unknown_worktree(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)

    with raises(WorktreeError, match="no worktree named"):
        remove(_settings(main), "demo")
