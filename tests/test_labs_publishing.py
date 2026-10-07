import json
import subprocess
from pathlib import Path

from pytest import raises

from deckz.exceptions import LabPublishRefusedError
from deckz.labs.publishing import publish

ID_PATTERN = r"[a-z0-9]+(-[a-z0-9]+)*"


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


def _write_notebook(path: Path, lab_id: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"shuuchuu": {"id": lab_id}} if lab_id else {}
    path.write_text(json.dumps({"cells": [], "metadata": metadata, "nbformat": 4}))


def _make_repos(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    _git(tmp_path, "init", "-b", "main", str(work))
    _write_notebook(
        work / "labs" / "notebooks" / "topic" / "demo-fr.ipynb", "topic-demo-fr"
    )
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Add demo notebook")
    _git(work, "remote", "add", "labs", str(remote))
    return remote, work


def _publish(work: Path, *, break_published_links: bool = False) -> bool:
    return publish(
        work,
        work / "labs" / "notebooks",
        id_metadata_key="shuuchuu.id",
        id_pattern=ID_PATTERN,
        remote="labs",
        branch="main",
        break_published_links=break_published_links,
    )


def test_publish_first_time_pushes_a_parentless_commit(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)

    published = _publish(work)

    assert published is True
    log = _git(work, "log", "--oneline", "labs/main").strip()
    assert len(log.splitlines()) == 1
    names = _git(work, "ls-tree", "-r", "--name-only", "labs/main").split()
    assert names == ["topic-demo-fr.ipynb"]


def test_publish_again_without_changes_is_a_noop(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)
    _publish(work)

    published = _publish(work)

    assert published is False


def test_publish_refuses_uncommitted_changes(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)
    (work / "labs" / "notebooks" / "topic" / "demo-fr.ipynb").write_text("{}")

    with raises(LabPublishRefusedError):
        _publish(work)


def test_publish_refuses_invalid_id(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)
    _write_notebook(
        work / "labs" / "notebooks" / "topic" / "bad-fr.ipynb", "Not Valid!"
    )
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Add invalid notebook")

    with raises(LabPublishRefusedError):
        _publish(work)


def test_publish_refuses_to_drop_published_links(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)
    _publish(work)
    (work / "labs" / "notebooks" / "topic" / "demo-fr.ipynb").unlink()
    _write_notebook(
        work / "labs" / "notebooks" / "topic" / "other-fr.ipynb", "topic-other-fr"
    )
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Rename notebook")

    with raises(LabPublishRefusedError):
        _publish(work)

    published = _publish(work, break_published_links=True)
    assert published is True
    names = _git(work, "ls-tree", "-r", "--name-only", "labs/main").split()
    assert names == ["topic-other-fr.ipynb"]
