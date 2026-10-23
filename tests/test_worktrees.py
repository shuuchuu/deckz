import os
import subprocess
from pathlib import Path

from pytest import raises

from deckz.configuring.settings import GlobalPaths, GlobalSettings, WorktreeSettings
from deckz.exceptions import WorktreeError
from deckz.stamps import digest, is_fresh, prune, stamp_path, write_stamp
from deckz.worktrees import (
    add,
    land,
    main_checkout,
    pending_renders,
    remove,
    worktrees,
)


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
        "/assets/built/*.svg\n/assets/built/*.png\n/assets/built/*.stamp\n/.env\n.venv/\n",
    )
    _write(main / "pyproject.toml", "[project]\n")
    _write(main / "uv.lock", "lock\n")
    _write(main / "assets" / "built" / "credits.yml", "author: Jane\n")
    _write(main / "figures" / "fig.typ", "Figure\n")
    _git(main, "add", "-A")
    _git(main, "commit", "-m", "Initial")
    # What git doesn't track: a build, and what's never copied.
    _write(main / "assets" / "built" / "fig.svg", "<svg/>")
    _write(main / "assets" / "built" / "fig.svg.stamp", "abc\n")
    _write(main / ".env", "DECKZ_LANG=fr\n")
    _write(main / ".venv" / "bin" / "python", "")
    return main


def _settings(git_dir: Path) -> GlobalSettings:
    return GlobalSettings(
        paths=GlobalPaths(current_dir=git_dir, git_dir=git_dir),
        worktree=WorktreeSettings(seed=("assets/built",)),
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
    assert not (added.path / ".env").exists()
    assert not (added.path / ".venv").exists()
    tracked = added.path / "assets" / "built" / "credits.yml"
    assert tracked.read_text(encoding="utf8") == "author: Jane\n"


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


def test_worktrees_lists_one_stopped_in_a_rebase(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path
    _write(path / "figures" / "fig.typ", "Mine\n")
    _git(path, "commit", "-am", "Mine")
    _write(main / "figures" / "fig.typ", "Theirs\n")
    _git(main, "commit", "-am", "Theirs")
    rebase = subprocess.run(
        ["git", "-C", str(path), "rebase", "main"], capture_output=True, check=False
    )
    assert rebase.returncode  # Stopped on the conflict, HEAD detached.

    (worktree,) = worktrees(_settings(main))

    assert worktree.name == "demo"
    assert worktree.branch == "ws/demo"
    assert "UU figures/fig.typ" in worktree.changes


def test_remove_deletes_a_clean_worktree_and_its_branch(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path

    removed = remove(_settings(main), "demo")

    assert not removed.kept_branch
    assert not path.exists()
    assert _git(main, "branch", "--list", "ws/demo") == ""


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
    removed = remove(_settings(main), "demo", force=True)

    assert removed.kept_branch
    assert not path.exists()
    assert _git(main, "branch", "--list", "ws/demo").strip() == "ws/demo"


def test_remove_counts_commits_merged_elsewhere_as_synced(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path
    _write(path / "figures" / "new.typ", "New\n")
    _git(path, "add", "figures/new.typ")
    _git(path, "commit", "-m", "New figure")
    _git(main, "merge", "--ff-only", "ws/demo")

    assert not remove(_settings(main), "demo").kept_branch


def test_remove_refuses_an_unknown_worktree(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)

    with raises(WorktreeError, match="no worktree named"):
        remove(_settings(main), "demo")


def _commit_in(path: Path, name: str) -> None:
    _write(path / "figures" / name, f"{name}\n")
    _git(path, "add", f"figures/{name}")
    _git(path, "commit", "-m", f"Add {name}")


def test_land_rebases_the_branch_and_fast_forwards_the_main_checkout(
    tmp_path: Path,
) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path
    _commit_in(path, "mine.typ")
    _commit_in(main, "theirs.typ")  # Another worktree's, landed meanwhile.

    branch, count, _ = land(_settings(path))

    assert (branch, count) == ("main", 1)
    assert (main / "figures" / "mine.typ").is_file()
    assert _git(main, "rev-parse", "HEAD") == _git(path, "rev-parse", "HEAD")
    assert _git(main, "rev-list", "--merges", "--count", "HEAD").strip() == "0"


def test_land_refuses_outside_a_worktree(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)

    with raises(WorktreeError, match="not in a worktree"):
        land(_settings(main))


def test_land_aborts_a_conflicting_rebase(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path
    for checkout in (path, main):
        _write(checkout / "figures" / "fig.typ", f"{checkout.name}\n")
        _git(checkout, "commit", "-am", "Change the figure")

    with raises(WorktreeError, match="rebase by hand"):
        land(_settings(main), "demo")
    assert (path / "figures" / "fig.typ").read_text(encoding="utf8") == "repo--demo\n"
    assert _git(path, "symbolic-ref", "--short", "HEAD").strip() == "ws/demo"


def _render(checkout: Path, name: str, text: str) -> Path:
    """Build `assets/built/<name>.svg` from `text`, stamped, with a poster.

    Returns:
        The output.
    """
    output = _write(checkout / "assets" / "built" / f"{name}.svg", text)
    _write(output.with_suffix(".png"), f"poster of {text}")
    write_stamp(output, digest([], text))
    return output


def test_land_copies_the_builds_the_main_checkout_lacks(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path
    _commit_in(path, "new.typ")
    _render(path, "new", "new figure")
    _render(path, "fig", "fig, rebuilt here")

    _, _, renders = land(_settings(path))

    assert renders.copied == ("assets/built/new.svg",)
    assert renders.set_aside == ()
    copy = main / "assets" / "built" / "new.svg"
    assert copy.read_text(encoding="utf8") == "new figure"
    assert copy.with_suffix(".png").read_text(encoding="utf8") == "poster of new figure"
    assert is_fresh(copy, digest([], "new figure"))
    # Never overwritten: only a build knows which of the two is up to date.
    assert (main / "assets" / "built" / "fig.svg").read_text(encoding="utf8") == (
        "<svg/>"
    )


def test_remove_copies_builds_and_sets_aside_those_main_holds_otherwise(
    tmp_path: Path,
) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path
    _render(path, "new", "new figure")
    _render(path, "fig", "fig, rebuilt here")
    _render(main, "same", "same")
    _render(path, "same", "same")

    pending = pending_renders(_settings(main), "demo")
    removed = remove(_settings(main), "demo")

    assert removed.renders == pending
    assert removed.renders.copied == ("assets/built/new.svg",)
    assert removed.renders.set_aside == ("assets/built/fig.svg",)
    fig = main / "assets" / "built" / "fig.svg"
    assert fig.read_text(encoding="utf8") == "<svg/>"
    # Once the main checkout's sources digest to the worktree's stamp (a pull),
    # its build adopts the copy set aside, poster included.
    stamp = digest([], "fig, rebuilt here")
    assert is_fresh(fig, stamp, companions=[fig.with_suffix(".png")])
    assert fig.read_text(encoding="utf8") == "fig, rebuilt here"
    assert fig.with_suffix(".png").read_text(encoding="utf8") == (
        "poster of fig, rebuilt here"
    )
    # The main checkout holds it now: the store lets it go.
    assert prune(main) == ["assets/built/fig.svg"]
    assert not (main / ".git" / "deckz" / "renders" / stamp).exists()


def test_pending_renders_changes_nothing(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path
    _render(path, "new", "new figure")
    _render(path, "fig", "fig, rebuilt here")

    pending = pending_renders(_settings(main), "demo")

    assert pending.copied == ("assets/built/new.svg",)
    assert pending.set_aside == ("assets/built/fig.svg",)
    assert not (main / "assets" / "built" / "new.svg").exists()
    assert not (main / ".git" / "deckz").exists()


def test_remove_sets_aside_nothing_another_checkout_holds(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path
    other = add(_settings(main), "other").path
    _render(path, "fig", "fig, rebuilt")
    _render(other, "fig", "fig, rebuilt")

    removed = remove(_settings(main), "demo")

    assert removed.renders.set_aside == ()
    assert stamp_path(other / "assets" / "built" / "fig.svg").is_file()


def test_prune_drops_what_is_older_than_its_days(tmp_path: Path) -> None:
    main = _make_repo(tmp_path)
    path = add(_settings(main), "demo").path
    _render(path, "fig", "fig, rebuilt here")
    remove(_settings(main), "demo")
    (entry,) = (main / ".git" / "deckz" / "renders").iterdir()

    assert prune(main) == []
    old = entry.stat().st_mtime - 31 * 86400
    os.utime(entry, (old, old))
    assert prune(main) == ["assets/built/fig.svg"]
    assert not entry.exists()
