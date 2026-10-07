from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from pytest import MonkeyPatch, raises

from deckz.exceptions import MissingExtraError
from deckz.videos import rendering
from deckz.videos.rendering import ensure_manim_installed, render_all, render_one
from deckz.videos.scenes import Render, Scene

_DEMO_SCENE = (
    "from manim import Circle, Scene\n\n\n"
    "class Demo(Scene):\n"
    "    def construct(self):\n"
    "        self.add(Circle())\n"
    "        self.wait(1)\n"
)

_FAILING_SCENE = (
    "from manim import Scene\n\n\n"
    "class Demo(Scene):\n"
    "    def construct(self):\n"
    '        raise RuntimeError("boom")\n'
)


def _scene_module(tmp_path: Path, source: str = _DEMO_SCENE) -> Path:
    scenes_dir = tmp_path / "figures" / "scenes"
    module = scenes_dir / "nn" / "demo.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(source, encoding="utf8")
    return module


class _CountingProgress:
    def __init__(self) -> None:
        self.advances = 0

    def track(
        self, description: str, total: int
    ) -> AbstractContextManager[Callable[[], None]]:
        @contextmanager
        def _ctx() -> Iterator[Callable[[], None]]:
            def advance() -> None:
                self.advances += 1

            yield advance

        return _ctx()


def test_render_one_renders_a_real_scene(tmp_path: Path) -> None:
    module = _scene_module(tmp_path)
    scene = Scene(module=module, name="Demo", video="nn/demo", languages=())
    video = tmp_path / "assets" / "videos" / "nn" / "demo.mp4"
    render = Render(scene=scene, language=None, file=video)

    error = render_one(render, "l", module.parent.parent)

    assert error is None
    assert video.is_file()
    assert video.with_suffix(".png").is_file()
    assert video.with_suffix(".quality").read_text(encoding="utf8") == "l"


def test_render_one_reports_an_error_for_a_failing_scene(tmp_path: Path) -> None:
    module = _scene_module(tmp_path, _FAILING_SCENE)
    scene = Scene(module=module, name="Demo", video="nn/demo", languages=())
    video = tmp_path / "assets" / "videos" / "nn" / "demo.mp4"
    render = Render(scene=scene, language=None, file=video)

    error = render_one(render, "l", module.parent.parent)

    assert error is not None
    assert "nn/demo" in error
    assert "boom" in error
    assert not video.exists()


def test_ensure_manim_installed_passes_when_present() -> None:
    ensure_manim_installed()  # Should not raise: manim is a dev dependency.


def test_ensure_manim_installed_raises_when_absent(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(rendering, "find_spec", lambda _name: None)

    with raises(MissingExtraError, match=r"deckz\[videos\]"):
        ensure_manim_installed()


def test_render_all_is_a_noop_for_no_renders(tmp_path: Path) -> None:
    assert render_all([], "l", tmp_path) == []


def test_render_all_raises_when_manim_is_missing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(rendering, "find_spec", lambda _name: None)
    module = _scene_module(tmp_path)
    scene = Scene(module=module, name="Demo", video="nn/demo", languages=())
    render = Render(scene=scene, language=None, file=tmp_path / "demo.mp4")

    with raises(MissingExtraError):
        render_all([render], "l", module.parent.parent)


def test_render_all_renders_and_reports_progress(tmp_path: Path) -> None:
    module = _scene_module(tmp_path)
    scene = Scene(module=module, name="Demo", video="nn/demo", languages=())
    video = tmp_path / "assets" / "videos" / "nn" / "demo.mp4"
    render = Render(scene=scene, language=None, file=video)
    progress = _CountingProgress()

    failed = render_all([render], "l", module.parent.parent, progress)

    assert failed == []
    assert video.is_file()
    assert progress.advances == 1


def test_render_all_aggregates_failures_without_raising(tmp_path: Path) -> None:
    module = _scene_module(tmp_path, _FAILING_SCENE)
    scene = Scene(module=module, name="Demo", video="nn/demo", languages=())
    render = Render(scene=scene, language=None, file=tmp_path / "demo.mp4")

    failed = render_all([render], "l", module.parent.parent)

    assert len(failed) == 1
