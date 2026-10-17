import json
from pathlib import Path
from typing import Any

from pygit2 import init_repository
from pytest import raises

from deckz.cli import main

_SCENE_SOURCE = (
    "from deckz.videos import register_scene\n\n\n"
    "@register_scene\n"
    "class Demo:\n"
    "    pass\n"
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")


def test_list_prints_nothing_without_any_scene(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    init_repository(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    main(("videos", "list"))

    assert capsys.readouterr().out == ""


def test_list_prints_a_line_per_render(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    init_repository(str(tmp_path))
    _write(tmp_path / "figures" / "scenes" / "nn" / "demo.py", _SCENE_SOURCE)
    monkeypatch.chdir(tmp_path)

    main(("videos", "list"))

    out = capsys.readouterr().out
    assert out == "-\tnn/demo.mp4\tDemo\tmissing\n"


def test_list_json_gives_each_render_its_state_and_scene(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    init_repository(str(tmp_path))
    _write(tmp_path / "figures" / "scenes" / "nn" / "demo.py", _SCENE_SOURCE)
    monkeypatch.chdir(tmp_path)

    main(("videos", "list", "--json"))

    assert json.loads(capsys.readouterr().out) == {
        "published_quality": "h",
        "renders": [
            {
                "video": "nn/demo",
                "scene": "Demo",
                "module": "figures/scenes/nn/demo.py",
                "line": 5,
                "sources": ["figures/scenes/nn/demo.py"],
                "language": None,
                "file": "assets/videos/nn/demo.mp4",
                "poster": "assets/videos/nn/demo.png",
                "quality": None,
                "state": "missing",
            }
        ],
    }


def test_render_exits_2_for_an_unknown_scene(tmp_path: Path, monkeypatch: Any) -> None:
    init_repository(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    with raises(SystemExit) as exc_info:
        main(("videos", "render", "nope"))

    assert exc_info.value.code == 2


def test_render_is_a_noop_without_any_scene(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    init_repository(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    main(("videos", "render"))

    assert capsys.readouterr().out == "every video is up to date\n"
