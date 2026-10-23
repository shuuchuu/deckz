import subprocess
from pathlib import Path

from deckz.upstream import missing, source, unpushed, upstream


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@e.x", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _clone(tmp_path: Path) -> tuple[Path, Path]:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", "-q", "-b", "main", str(origin))
    _git(tmp_path, "init", "-q", "-b", "main", str(work))
    (work / "a.txt").write_text("a\n")
    _git(work, "add", "a.txt")
    _git(work, "commit", "-qm", "First")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "-u", "origin", "main")
    return origin, work


def test_a_worktree_takes_its_main_checkout_s_upstream(tmp_path: Path) -> None:
    _origin, work = _clone(tmp_path)
    worktree = tmp_path / "work--topic"
    _git(work, "worktree", "add", "-q", "-b", "ws/topic", str(worktree))

    found = upstream(worktree)

    assert found is not None
    assert found.name == "origin/main"
    assert found.tracking == "refs/remotes/origin/main"


def test_source_is_head_without_an_upstream(tmp_path: Path) -> None:
    _origin, work = _clone(tmp_path)
    _git(work, "branch", "--unset-upstream")

    found = source(work)

    assert found.name == "HEAD"
    assert found.commit == _git(work, "rev-parse", "HEAD")


def test_source_fetches_what_another_clone_pushed(tmp_path: Path) -> None:
    origin, work = _clone(tmp_path)
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(origin), str(other))
    (other / "a.txt").write_text("b\n")
    _git(other, "commit", "-qam", "Second")
    _git(other, "push", "-q")

    assert source(work, fetch_first=False).commit == _git(work, "rev-parse", "HEAD")
    found = source(work)

    assert found.commit == _git(other, "rev-parse", "HEAD")
    assert missing(work, found.commit, ["a.txt"]) == [
        f"{_git(other, 'rev-parse', '--short', 'HEAD')} Second"
    ]


def test_unpushed_lists_head_s_commits_on_the_paths_only(tmp_path: Path) -> None:
    _origin, work = _clone(tmp_path)
    (work / "a.txt").write_text("c\n")
    _git(work, "commit", "-qam", "Change a")
    (work / "b.txt").write_text("b\n")
    _git(work, "add", "b.txt")
    _git(work, "commit", "-qm", "Add b")
    base = _git(work, "rev-parse", "origin/main")

    assert [line.split(" ", 1)[1] for line in unpushed(work, base, ["a.txt"])] == [
        "Change a"
    ]
