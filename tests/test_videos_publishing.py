import subprocess
from pathlib import Path
from typing import Any

from pytest import raises

from deckz.exceptions import VideoFetchError, VideoPublishRefusedError
from deckz.stamps import digest, write_stamp
from deckz.videos.publishing import (
    FetchResult,
    differing_sources,
    fetch_published,
    fetch_renders,
    publish,
    publishable,
    published_blobs,
    unpublished_reason,
)
from deckz.videos.scenes import Render, Scene, state

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


def _reason(work: Path, published: dict[str, str]) -> str | None:
    videos = work / "assets" / "videos"
    return unpublished_reason(
        work, videos, videos / "nn" / "demo.mp4", published, wanted_quality=QUALITY
    )


def test_unpublished_reason_follows_the_render_and_its_published_blob(
    tmp_path: Path,
) -> None:
    _remote, work = _make_repos(tmp_path)
    assert published_blobs(work, None) == {}
    assert _reason(work, {}) == "nn/demo.mp4 is not published"

    _fake_render(work)
    _publish(work, _preview(work))
    published = published_blobs(work, fetch_published(work, "videos", "main"))
    assert set(published) == {".nojekyll", "nn/demo.mp4"}
    assert _reason(work, published) is None

    _fake_render(work, size=2000)
    assert _reason(work, published) == "nn/demo.mp4 differs from its published version"
    _fake_render(work, quality="l")
    assert _reason(work, published) == "nn/demo.mp4 is a draft render"


def _fetch(work: Path, source: str = "videos") -> FetchResult:
    return fetch_renders(
        work,
        work / "assets" / "videos",
        [_scene(work)],
        source=source,
        branch="main",
        quality=QUALITY,
    )


def _poster(video: Path) -> None:
    video.with_suffix(".png").write_bytes(b"poster")


def test_fetch_renders_puts_a_published_render_in_place(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from deckz.videos import rendering

    monkeypatch.setattr(rendering, "make_poster", _poster)
    remote, work = _make_repos(tmp_path)
    video = _fake_render(work, size=10)
    _publish(work, _preview(work))
    for suffix in (".mp4", ".png", ".quality"):
        video.with_suffix(suffix).unlink()

    result = _fetch(work, str(remote))  # A URL works as well as a remote.

    assert result.fetched == (video,)
    assert video.read_bytes() == b"\0" * 10
    assert video.with_suffix(".png").read_bytes() == b"poster"
    assert video.with_suffix(".quality").read_text() == QUALITY
    # No sources stamp: `deckz videos render` takes it for stale.
    assert state(Render(_scene(work), None, video), QUALITY) == "stale"


def test_fetch_renders_never_replaces_a_render(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from deckz.videos import rendering

    monkeypatch.setattr(rendering, "make_poster", _poster)
    _, work = _make_repos(tmp_path)
    video = _fake_render(work, size=10)
    _publish(work, _preview(work))
    video.write_bytes(b"mine")

    assert _fetch(work) == FetchResult((), (), ())
    assert video.read_bytes() == b"mine"


def test_fetch_renders_copies_a_render_up_to_date_in_another_checkout(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from deckz.videos import rendering

    monkeypatch.setattr(rendering, "make_poster", _poster)
    _, work = _make_repos(tmp_path)
    video = _fake_render(work, size=10)
    write_stamp(video, digest(_scene(work).sources()))
    _publish(work, _preview(work))
    worktree = tmp_path / "work--ws"
    _git(work, "worktree", "add", "--quiet", "-b", "ws/ws", str(worktree))

    assert _fetch(worktree) == FetchResult((), (), ())
    copied = worktree / "assets" / "videos" / "nn" / "demo.mp4"
    assert copied.read_bytes() == b"\0" * 10
    assert state(Render(_scene(worktree), None, copied), QUALITY) == "fresh"


def test_fetch_renders_lists_what_was_never_published(tmp_path: Path) -> None:
    _, work = _make_repos(tmp_path)
    _fake_render(work)
    _publish(work, _preview(work))
    other = Scene(
        module=_scene(work).module, name="Other", video="nn/other", languages=()
    )

    result = fetch_renders(
        work,
        work / "assets" / "videos",
        [_scene(work), other],
        source="videos",
        branch="main",
        quality=QUALITY,
    )

    assert result.unpublished == ("nn/other.mp4",)


def test_fetch_renders_names_the_fix_when_it_cant_fetch(tmp_path: Path) -> None:
    _, work = _make_repos(tmp_path)

    with raises(VideoFetchError, match=r"videos\.publish_remote"):
        _fetch(work, str(tmp_path / "nowhere"))


def test_differing_sources_names_the_scene_sources_another_commit_has_otherwise(
    tmp_path: Path,
) -> None:
    _remote, work = _make_repos(tmp_path)
    base = _git(work, "rev-parse", "HEAD").strip()
    scenes_dir = work / "figures" / "scenes"

    assert differing_sources(work, scenes_dir, [_scene(work)], base) == []

    # Newer upstream: a scene changed, and one added.
    _write(scenes_dir / "nn" / "demo.py", _SCENE_SOURCE + "# changed\n")
    _write(scenes_dir / "nn" / "other.py", _SCENE_SOURCE)
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Change the scenes")
    newer = _git(work, "rev-parse", "HEAD").strip()
    _git(work, "checkout", "-q", base)

    assert differing_sources(work, scenes_dir, [_scene(work)], newer) == [
        "figures/scenes/nn/demo.py",
        "figures/scenes/nn/other.py",
    ]


def test_publish_command_refuses_scene_sources_other_than_the_upstream_s(
    tmp_path: Path, monkeypatch: Any, caplog: Any
) -> None:
    import appdirs

    from deckz.cli import main

    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_path))
    remote, work = _make_repos(tmp_path)
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "--quiet", "-u", "origin", "main")
    stale = tmp_path / "work--stale"
    _git(work, "worktree", "add", "-q", "-b", "ws/stale", str(stale))
    _write(work / "figures" / "scenes" / "nn" / "demo.py", _SCENE_SOURCE + "# v2\n")
    _git(work, "commit", "-qam", "Change the demo scene")
    _git(work, "push", "--quiet", "origin", "main")

    with raises(SystemExit) as exc_info:
        main(("videos", "publish", "--workdir", str(stale)))

    assert exc_info.value.code == 1
    assert (
        "the scenes' sources here differ from origin/main's: figures/scenes/nn/demo.py"
    ) in caplog.text
    assert "update this checkout to origin/main" in caplog.text
    assert not _git(remote, "branch", "--list")
