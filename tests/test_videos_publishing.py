import subprocess
from pathlib import Path

from pytest import raises

from deckz.exceptions import VideoPublishRefusedError
from deckz.videos.publishing import publish, publishable
from deckz.videos.scenes import Scene

QUALITY = "h"
MAX_SIZE = 100_000_000
WARN_SIZE = 50_000_000

_SCENE_SOURCE = (
    "from deckz.videos import register_scene\n\n\n"
    "@register_scene\n"
    "class Demo:\n"
    "    pass\n"
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


def _write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf8")


def _make_repos(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    _git(tmp_path, "init", "-b", "main", str(work))
    _write(work / "figures" / "scenes" / "nn" / "demo.py", _SCENE_SOURCE)
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Add demo scene")
    _git(work, "remote", "add", "videos", str(remote))
    return remote, work


def _scene(work: Path) -> Scene:
    return Scene(
        module=work / "figures" / "scenes" / "nn" / "demo.py",
        name="Demo",
        video="nn/demo",
        languages=(),
    )


def _fake_render(work: Path, *, size: int = 1000, quality: str = QUALITY) -> Path:
    video = work / "assets" / "videos" / "nn" / "demo.mp4"
    _write(video, b"\0" * size)
    _write(video.with_suffix(".png"), b"poster")
    _write(video.with_suffix(".quality"), quality)
    return video


def _preview(work: Path, *, max_size: int = MAX_SIZE, warn_size: int = WARN_SIZE):
    return publishable(
        [_scene(work)],
        work / "assets" / "videos",
        quality=QUALITY,
        max_size=max_size,
        warn_size=warn_size,
    )


def _publish(work: Path, preview, *, break_published_links: bool = False) -> bool:
    return publish(
        work,
        work / "figures" / "scenes",
        preview,
        remote="videos",
        branch="main",
        break_published_links=break_published_links,
    )


def test_publishable_reports_a_missing_render_as_a_problem(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)

    preview = _preview(work)

    assert preview.site == {}
    assert len(preview.problems) == 1
    assert "nn/demo.mp4" in preview.problems[0]


def test_publishable_includes_a_ready_render(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)
    _fake_render(work)

    preview = _preview(work)

    assert set(preview.site) == {"nn/demo.mp4"}
    assert preview.problems == ()
    assert preview.warnings == ()


def test_publishable_flags_an_oversized_render_as_a_problem(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)
    _fake_render(work, size=200)

    preview = _preview(work, max_size=100, warn_size=50)

    assert preview.site == {}
    assert len(preview.problems) == 1
    assert "nn/demo.mp4" in preview.problems[0]


def test_publishable_warns_but_still_includes_a_large_render(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)
    _fake_render(work, size=80)

    preview = _preview(work, max_size=100, warn_size=50)

    assert set(preview.site) == {"nn/demo.mp4"}
    assert len(preview.warnings) == 1
    assert "nn/demo.mp4" in preview.warnings[0]


def test_publish_refuses_when_preview_has_problems(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)
    preview = _preview(work)

    with raises(VideoPublishRefusedError):
        _publish(work, preview)


def test_publish_refuses_uncommitted_scene_changes(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)
    _fake_render(work)
    preview = _preview(work)
    (work / "figures" / "scenes" / "nn" / "demo.py").write_text(
        _SCENE_SOURCE + "\n# edited\n", encoding="utf8"
    )

    with raises(VideoPublishRefusedError):
        _publish(work, preview)


def test_publish_first_time_pushes_a_parentless_commit(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)
    _fake_render(work)
    preview = _preview(work)

    published = _publish(work, preview)

    assert published is True
    log = _git(work, "log", "--oneline", "videos/main").strip()
    assert len(log.splitlines()) == 1
    names = set(_git(work, "ls-tree", "-r", "--name-only", "videos/main").split())
    assert names == {".nojekyll", "nn/demo.mp4"}


def test_publish_again_without_changes_is_a_noop(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)
    _fake_render(work)
    preview = _preview(work)
    _publish(work, preview)

    published = _publish(work, preview)

    assert published is False


def test_publish_refuses_to_drop_a_published_link(tmp_path: Path) -> None:
    _remote, work = _make_repos(tmp_path)
    _fake_render(work)
    _publish(work, _preview(work))

    # Replace the scene with a differently-named one, committed.
    (work / "figures" / "scenes" / "nn" / "demo.py").unlink()
    _write(
        work / "figures" / "scenes" / "nn" / "other.py",
        _SCENE_SOURCE.replace("class Demo", "class Other"),
    )
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Rename scene")
    other_scene = Scene(
        module=work / "figures" / "scenes" / "nn" / "other.py",
        name="Other",
        video="nn/other",
        languages=(),
    )
    video = work / "assets" / "videos" / "nn" / "other.mp4"
    _write(video, b"\0" * 1000)
    _write(video.with_suffix(".png"), b"poster")
    _write(video.with_suffix(".quality"), QUALITY)
    preview = publishable(
        [other_scene],
        work / "assets" / "videos",
        quality=QUALITY,
        max_size=MAX_SIZE,
        warn_size=WARN_SIZE,
    )

    with raises(VideoPublishRefusedError):
        _publish(work, preview)

    published = _publish(work, preview, break_published_links=True)
    assert published is True
    names = set(_git(work, "ls-tree", "-r", "--name-only", "videos/main").split())
    assert names == {".nojekyll", "nn/other.mp4"}
