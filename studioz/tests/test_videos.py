import json
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

from fastapi.testclient import TestClient
from pytest import fixture
from studioz.jobs import JobState
from studioz.videos import BASELINES_DIR

ORIGIN = {"Origin": "http://localhost:8421"}
BASE = "/espaces/demo"
KEPT = BASELINES_DIR.as_posix()

_SCENE = (
    "from deckz.videos import register_scene\n\n\n"
    '@register_scene(languages=("fr", "en"))\n'
    "class Demo:\n"
    "    pass\n"
)

# Stands for the workspace's own deckz: the real one, but for `videos render`,
# which writes what deckz's render would (the video, its poster, its quality
# and its stamp) without Manim.
_FAKE_DECKZ = f"""#!{sys.executable}
import sys
from pathlib import Path

args = sys.argv[1:]
if args[:2] == ["videos", "render"]:
    from deckz.configuring.settings import GlobalSettings
    from deckz.stamps import digest, write_stamp
    from deckz.videos import renders, scenes

    settings = GlobalSettings.from_yaml(Path())
    quality = args[args.index("--quality") + 1]
    for scene in scenes(settings):
        if scene.video != args[2]:
            continue
        for render in renders(settings.paths.videos_dir, scene):
            render.file.parent.mkdir(parents=True, exist_ok=True)
            source = scene.module.read_text(encoding="utf8")
            # Moved into place, as deckz does.
            new = render.file.with_suffix(".new")
            new.write_text(f"{{quality}} {{source}}", encoding="utf8")
            new.replace(render.file)
            render.file.with_suffix(".png").write_bytes(b"poster")
            render.file.with_suffix(".quality").write_text(quality, encoding="utf8")
            write_stamp(render.file, digest(scene.sources()))
    print("rendered", args[2], "at", quality)
else:
    from deckz.cli import main

    main(args)
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@fixture
def scene(workspace: Path, repository: Path) -> Path:
    (repository / ".git" / "info" / "exclude").write_text(
        ".venv/\n/assets/videos/\n", encoding="utf8"
    )
    deckz = workspace / ".venv" / "bin" / "deckz"
    deckz.parent.mkdir(parents=True)
    deckz.write_text(_FAKE_DECKZ, encoding="utf8")
    deckz.chmod(0o755)
    module = workspace / "figures" / "scenes" / "nn" / "demo.py"
    module.parent.mkdir(parents=True)
    module.write_text(_SCENE, encoding="utf8")
    _git(workspace, "add", "figures")
    _git(workspace, "commit", "-m", "Add a scene")
    return module


def _render(client: TestClient, *, final: bool = False) -> str:
    response = client.post(
        f"{BASE}/videos/nn/demo/rendre",
        data={"final": "true"} if final else {},
        headers=ORIGIN,
    )
    assert json.loads(response.headers["HX-Trigger-After-Settle"]) == {
        "jobs-changed": None,
        "job-started": None,
    }
    job = client.app.state.studio.jobs._jobs[-1]  # pyrefly: ignore[missing-attribute]
    deadline = monotonic() + 30
    while not job.finished:
        assert monotonic() < deadline, "the render never finished"
        sleep(0.05)
    assert job.state is JobState.DONE, list(job.log)
    return job.title


def _player(client: TestClient, **params: str) -> str:
    response = client.get(f"{BASE}/videos/nn/demo/lecteur", params=params)
    assert response.status_code == 200
    return response.text


def test_the_view_lists_each_scene_and_its_state(
    scene: Path, client: TestClient
) -> None:
    view = client.get(f"{BASE}/videos").text

    assert f'href="{BASE}/videos/nn/demo"' in view
    assert "jamais rendue" in view
    assert '<span class="count" title="Les vidéos jamais rendues' in view
    assert ">1</span>" in view


def test_a_draft_then_its_before_and_after(
    scene: Path, workspace: Path, client: TestClient
) -> None:
    assert "Jamais rendue" in _player(client)

    title = _render(client)

    assert title == "Brouillon de la vidéo nn/demo (l)"
    player = _player(client)
    assert "fr : brouillon (l)" in player
    assert f'src="{BASE}/rendus/assets/videos/nn/demo.mp4?v=' in player
    # Up to date with the scene: a draft would show nothing new.
    assert 'data-render="draft" hx-post' in player
    assert 'disabled title="Les rendus suivent déjà la scène' in player
    video = client.get(f"{BASE}/rendus/assets/videos/nn/demo.mp4")
    assert video.text.startswith("l from deckz")
    # The scene is the last commit's: so is its render, kept for later.
    assert "son rendu est celui du commit" in _player(client, vue="avant-apres")
    kept = sorted((workspace / BASELINES_DIR).rglob("demo.mp4"))
    assert len(kept) == 2  # fr and en
    # A hard link: no space taken.
    assert kept[0].samefile(workspace / "assets" / "videos" / "nn" / "demo.mp4")

    scene.write_text(_SCENE + "    # Changed.\n", encoding="utf8")
    changed = _player(client, vue="avant-apres")
    assert "Pas encore rendue telle qu'elle est" in changed
    before = changed.split(f'src="{BASE}/rendus/')[1].split("?")[0]
    assert before.startswith(f"{KEPT}/")
    _render(client)
    after = _player(client, vue="avant-apres")
    assert after.count("<video") == 2
    assert client.get(f"{BASE}/rendus/{before}").text == f"l {_SCENE}"
    assert "# Changed." in client.get(f"{BASE}/rendus/assets/videos/nn/demo.mp4").text
    # In English, its own render.
    assert "/rendus/assets/videos/nn/en/demo.mp4" in _player(client, lang="en")


def test_a_final_render_at_the_published_quality(
    scene: Path, client: TestClient
) -> None:
    title = _render(client, final=True)

    assert title == "Rendu final de la vidéo nn/demo (h)"
    job = client.app.state.studio.jobs._jobs[-1]  # pyrefly: ignore[missing-attribute]
    assert job.steps[0][-4:] == ("render", "nn/demo", "--quality", "h")
    assert "à jour" in client.get(f"{BASE}/videos").text
    player = _player(client)
    assert player.count("disabled") == 2


def test_only_renders_are_served(scene: Path, client: TestClient) -> None:
    _render(client)

    for file in (
        "figures/scenes/nn/demo.py",
        "assets/videos/../../figures/scenes/nn/demo.py",
        ".git/HEAD",
        "assets/videos/nn/missing.mp4",
    ):
        assert client.get(f"{BASE}/rendus/{file}").status_code == 404, file


def test_the_page_and_its_module_in_the_editor(scene: Path, client: TestClient) -> None:
    page = client.get(f"{BASE}/videos/nn/demo")
    assert page.status_code == 200
    assert f'hx-get="{BASE}/videos/nn/demo/lecteur?lang=fr"' in page.text
    assert 'data-view="videos"' in page.text

    player = _player(client)
    assert 'data-module="figures/scenes/nn/demo.py" data-line="5"' in player
    source = client.get(f"{BASE}/fichiers/figures/scenes/nn/demo.py")
    assert source.json()["text"] == _SCENE
    assert client.get(f"{BASE}/videos/nn/missing/lecteur").status_code == 404
