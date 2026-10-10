import json
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import raises
from studioz.sources import ChangedOnDiskError, read, save, source

ORIGIN = {"Origin": "http://localhost:8421"}
FILES = "/espaces/demo/fichiers"


def _content(workspace: Path) -> Path:
    path = workspace / "content" / "greeting" / "hello.md"
    path.parent.mkdir(parents=True)
    path.write_text("Intro\n# Hello\n\nText\n", encoding="utf8")
    return path


def test_only_the_material_is_editable(workspace: Path) -> None:
    hello = _content(workspace)
    (workspace / ".git-notes.md").write_text("x", encoding="utf8")
    (workspace / "dodo.py").write_text("x", encoding="utf8")

    assert source(workspace, "content/greeting/hello.md") == hello
    assert source(workspace, "client/abc/deck.yml") is not None
    for file in (
        "",
        "dodo.py",
        ".git-notes.md",
        ".git/HEAD",
        "content/missing.md",
        "../repo/client/abc/deck.yml",
        str(hello),
    ):
        assert source(workspace, file) is None, file


def test_a_save_names_the_version_it_replaces(workspace: Path) -> None:
    hello = _content(workspace)
    text, version = read(hello)

    new = save(hello, text + "More\n", version)

    assert hello.read_text(encoding="utf8").endswith("Text\nMore\n")
    assert read(hello)[1] == new != version
    with raises(ChangedOnDiskError) as error:
        save(hello, "stale", version)
    assert error.value.version == new
    assert hello.read_text(encoding="utf8").endswith("More\n")
    # The temporary file is gone.
    assert [p.name for p in hello.parent.iterdir()] == ["hello.md"]


def test_open_then_save(client: TestClient, workspace: Path) -> None:
    hello = _content(workspace)

    opened = client.get(f"{FILES}/content/greeting/hello.md").json()
    assert opened["text"] == "Intro\n# Hello\n\nText\n"

    saved = client.post(
        f"{FILES}/content/greeting/hello.md",
        data={"text": "# Bonjour\n", "version": opened["version"]},
        headers=ORIGIN,
    )
    assert saved.status_code == 200
    assert hello.read_text(encoding="utf8") == "# Bonjour\n"

    conflict = client.post(
        f"{FILES}/content/greeting/hello.md",
        data={"text": "# Stale\n", "version": opened["version"]},
        headers=ORIGIN,
    )
    assert conflict.status_code == 409
    assert conflict.json() == {"version": saved.json()["version"]}
    assert hello.read_text(encoding="utf8") == "# Bonjour\n"

    emptied = client.post(
        f"{FILES}/content/greeting/hello.md",
        data={"text": "", "version": saved.json()["version"]},
        headers=ORIGIN,
    )
    assert emptied.status_code == 200
    assert hello.read_text(encoding="utf8") == ""


def test_refused_files(client: TestClient, workspace: Path) -> None:
    assert client.get(f"{FILES}/dodo.py").status_code == 404
    assert client.get(f"{FILES}/.git/HEAD").status_code == 404
    response = client.post(
        f"{FILES}/.gitignore", data={"text": "", "version": "x"}, headers=ORIGIN
    )
    assert response.status_code == 404
    # A change from another site is refused before anything else.
    response = client.post(
        f"{FILES}/client/abc/deck.yml", data={"text": "", "version": "x"}
    )
    assert response.status_code == 403


def test_frames_from_what_the_build_recorded(
    client: TestClient, workspace: Path
) -> None:
    _content(workspace)
    url = "/espaces/demo/formations/client/abc/cadres"
    assert client.get(url).json()["frames"] == []
    assert "build" in client.get(url).json()["error"]

    deck = workspace / "client" / "abc"
    build = deck / ".build" / "abc-handout"
    fragment = build / "greeting" / "hello-0123456789abcdef.md"
    fragment.parent.mkdir(parents=True)
    fragment.write_text("Intro\n# Hello\n\nText\n", encoding="utf8")
    (build / "abc-handout.typ").write_text("", encoding="utf8")
    (build / "abc-handout.pdf").write_bytes(b"%PDF-1.4")
    (deck / "pdf").mkdir()
    (deck / "pdf" / "abc-handout.pdf").write_bytes(b"%PDF-1.4")
    markers = {"deckz-frame": [{"fragment": str(fragment), "index": 0, "page": 3}]}
    (build / "abc-handout.markers.json").write_text(json.dumps(markers), "utf8")

    hello = {"title": "Hello", "file": "content/greeting/hello.md", "line": 2}
    assert client.get(url).json() == {"frames": [{"page": 3, **hello}]}
