import os
from pathlib import Path

from pygit2 import init_repository
from pytest import raises

from deckz.configuring.settings import GlobalPaths, GlobalSettings
from deckz.exceptions import VideoSceneError
from deckz.stamps import digest, write_stamp
from deckz.videos.scenes import out_of_date, quality, renders, scenes, video_file


def _settings(git_dir: Path) -> GlobalSettings:
    return GlobalSettings(paths=GlobalPaths(current_dir=git_dir, git_dir=git_dir))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")


_SIMPLE_SCENE = (
    "from deckz.videos import register_scene\n\n\n"
    "@register_scene\n"
    "class Demo:\n"
    "    pass\n"
)


def test_scenes_finds_a_plain_register_scene(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "figures" / "scenes" / "nn" / "causal_mask.py",
        "from deckz.videos import register_scene\n\n\n"
        "@register_scene\n"
        "class CausalMask:\n"
        "    pass\n",
    )

    found = scenes(_settings(tmp_path))

    assert len(found) == 1
    assert found[0].name == "CausalMask"
    assert found[0].video == "nn/causal-mask"
    assert found[0].languages == ()


def test_scenes_finds_languages(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "figures" / "scenes" / "nn" / "demo.py",
        "from deckz.videos import register_scene\n\n\n"
        '@register_scene(languages=("fr", "en"))\n'
        "class Demo:\n"
        "    pass\n",
    )

    found = scenes(_settings(tmp_path))

    assert found[0].languages == ("fr", "en")


def test_scenes_ignores_undecorated_classes(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "figures" / "scenes" / "nn" / "demo.py",
        "class NotAScene:\n    pass\n",
    )

    assert scenes(_settings(tmp_path)) == []


def test_scenes_raises_on_positional_languages(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "figures" / "scenes" / "nn" / "demo.py",
        "from deckz.videos import register_scene\n\n\n"
        '@register_scene("fr")\n'
        "class Demo:\n"
        "    pass\n",
    )

    with raises(VideoSceneError):
        scenes(_settings(tmp_path))


def test_scenes_raises_on_unknown_language(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "figures" / "scenes" / "nn" / "demo.py",
        "from deckz.videos import register_scene\n\n\n"
        '@register_scene(languages=("de",))\n'
        "class Demo:\n"
        "    pass\n",
    )

    with raises(VideoSceneError):
        scenes(_settings(tmp_path))


def test_video_file_default_language_path(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "figures" / "scenes" / "nn" / "demo.py",
        _SIMPLE_SCENE,
    )
    settings = _settings(tmp_path)

    path = video_file(settings, "nn/demo", "fr")

    assert path == settings.paths.videos_dir / "nn" / "demo.mp4"


def test_video_file_per_language_path(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "figures" / "scenes" / "nn" / "demo.py",
        "from deckz.videos import register_scene\n\n\n"
        '@register_scene(languages=("fr", "en"))\n'
        "class Demo:\n"
        "    pass\n",
    )
    settings = _settings(tmp_path)

    fr = video_file(settings, "nn/demo", "fr")
    en = video_file(settings, "nn/demo", "en")

    assert fr == settings.paths.videos_dir / "nn" / "demo.mp4"
    assert en == settings.paths.videos_dir / "nn" / "en" / "demo.mp4"


def test_video_file_raises_for_unknown_video(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    settings = _settings(tmp_path)

    with raises(LookupError):
        video_file(settings, "nn/nope", "fr")


def test_video_file_raises_for_missing_language(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    _write(
        tmp_path / "figures" / "scenes" / "nn" / "demo.py",
        "from deckz.videos import register_scene\n\n\n"
        '@register_scene(languages=("fr",))\n'
        "class Demo:\n"
        "    pass\n",
    )
    settings = _settings(tmp_path)

    with raises(LookupError):
        video_file(settings, "nn/demo", "en")


def test_out_of_date_true_when_missing(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    module = tmp_path / "figures" / "scenes" / "nn" / "demo.py"
    _write(
        module,
        _SIMPLE_SCENE,
    )
    settings = _settings(tmp_path)
    scene = scenes(settings)[0]
    render = renders(settings.paths.videos_dir, scene)[0]

    assert out_of_date(render, "h")


def test_out_of_date_false_when_current(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    module = tmp_path / "figures" / "scenes" / "nn" / "demo.py"
    _write(
        module,
        _SIMPLE_SCENE,
    )
    settings = _settings(tmp_path)
    scene = scenes(settings)[0]
    render = renders(settings.paths.videos_dir, scene)[0]
    render.file.parent.mkdir(parents=True, exist_ok=True)
    render.file.write_bytes(b"video")
    render.file.with_suffix(".png").write_bytes(b"poster")
    render.file.with_suffix(".quality").write_text("h", encoding="utf8")
    future = module.stat().st_mtime_ns + 2_000_000_000
    os.utime(render.file, ns=(future, future))
    os.utime(render.file.with_suffix(".png"), ns=(future, future))

    assert not out_of_date(render, "h")


def test_out_of_date_true_when_quality_differs(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    module = tmp_path / "figures" / "scenes" / "nn" / "demo.py"
    _write(
        module,
        _SIMPLE_SCENE,
    )
    settings = _settings(tmp_path)
    scene = scenes(settings)[0]
    render = renders(settings.paths.videos_dir, scene)[0]
    render.file.parent.mkdir(parents=True, exist_ok=True)
    render.file.write_bytes(b"video")
    render.file.with_suffix(".png").write_bytes(b"poster")
    render.file.with_suffix(".quality").write_text("l", encoding="utf8")

    assert out_of_date(render, "h")


def test_quality_is_none_without_a_stamp(tmp_path: Path) -> None:
    assert quality(tmp_path / "demo.mp4") is None


def _rendered(render_file: Path, quality: str = "h") -> None:
    render_file.parent.mkdir(parents=True, exist_ok=True)
    render_file.write_bytes(b"video")
    render_file.with_suffix(".png").write_bytes(b"poster")
    render_file.with_suffix(".quality").write_text(quality, encoding="utf8")


def test_out_of_date_false_when_stamped_whatever_the_times(tmp_path: Path) -> None:
    # A checkout makes the module look newer than its render.
    init_repository(str(tmp_path))
    module = tmp_path / "figures" / "scenes" / "nn" / "demo.py"
    _write(module, _SIMPLE_SCENE)
    settings = _settings(tmp_path)
    scene = scenes(settings)[0]
    render = renders(settings.paths.videos_dir, scene)[0]
    _rendered(render.file)
    write_stamp(render.file, digest(scene.sources()))
    future = render.file.stat().st_mtime_ns + 2_000_000_000
    os.utime(module, ns=(future, future))

    assert not out_of_date(render, "h")


def test_out_of_date_true_when_an_imported_helper_changed(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    scenes_dir = tmp_path / "figures" / "scenes"
    _write(scenes_dir / "__init__.py", "")
    lesson = scenes_dir / "lesson.py"
    _write(lesson, "TITLE = 1\n")
    _write(
        scenes_dir / "nn" / "demo.py",
        "from scenes.lesson import TITLE\n" + _SIMPLE_SCENE,
    )
    settings = _settings(tmp_path)
    scene = scenes(settings)[0]
    render = renders(settings.paths.videos_dir, scene)[0]
    _rendered(render.file)
    write_stamp(render.file, digest(scene.sources()))

    assert lesson in scene.sources()
    assert not out_of_date(render, "h")
    lesson.write_text("TITLE = 2\n", encoding="utf8")
    assert out_of_date(render, "h")
