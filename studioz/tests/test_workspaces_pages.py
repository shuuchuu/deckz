import subprocess
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from studioz.workspaces import DeckFolder, deck_tree

ORIGIN = {"Origin": "http://localhost:8421"}


def _branch(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _create(client: TestClient, monkeypatch: Any, name: str = "demo") -> Any:
    # `deckz setup` checks the machine (pandoc…): not this test's business.
    monkeypatch.setattr("studioz.workspaces.setup", lambda *_, **__: [])
    return client.post("/espaces", data={"name": name}, headers=ORIGIN)


def test_home_without_workspaces(client: TestClient) -> None:
    response = client.get("/")

    assert "Aucun espace de travail" in response.text
    assert "Nouvel espace de travail" in response.text


def test_create_opens_the_workspace(
    client: TestClient, repository: Path, monkeypatch: Any
) -> None:
    response = _create(client, monkeypatch)

    assert response.headers["HX-Redirect"] == "/espaces/demo"
    path = repository.parent / "repo--demo"
    assert _branch(path) == "ws/demo"
    home = client.get("/").text
    assert 'href="/espaces/demo"' in home


def test_create_refuses_an_invalid_name(client: TestClient, monkeypatch: Any) -> None:
    response = _create(client, monkeypatch, "../x")

    assert "invalid worktree name" in response.text
    assert "HX-Redirect" not in response.headers


def test_create_shows_what_setup_left_missing(
    client: TestClient, monkeypatch: Any
) -> None:
    from deckz.setting_up import SetupItem, Status

    missing = [SetupItem("uv sync", Status.FAILED, "`uv sync` exited 2")]
    monkeypatch.setattr("studioz.workspaces.setup", lambda *_, **__: missing)

    response = client.post("/espaces", data={"name": "demo"}, headers=ORIGIN)

    assert "`uv sync` exited 2" in response.text
    assert 'href="/espaces/demo"' in response.text


def test_create_opens_a_workspace_the_machine_lacks_a_tool_for(
    client: TestClient, monkeypatch: Any
) -> None:
    from deckz.setting_up import SetupItem, Status

    missing = [SetupItem("xelatex", Status.MISSING, "install it", shared=True)]
    monkeypatch.setattr("studioz.workspaces.setup", lambda *_, **__: missing)

    response = client.post("/espaces", data={"name": "demo"}, headers=ORIGIN)

    assert response.headers["HX-Redirect"] == "/espaces/demo"


def test_workspace_page_lists_decks_and_changes(
    client: TestClient, repository: Path, monkeypatch: Any
) -> None:
    _create(client, monkeypatch)
    (repository.parent / "repo--demo" / "notes.md").write_text("x", encoding="utf8")

    page = client.get("/espaces/demo").text

    assert "client/abc" in page
    assert 'hx-get="/espaces/demo/modifications"' in page
    assert "notes.md" in client.get("/espaces/demo/modifications").text
    assert (repository.parent / "repo--demo" / ".run/studioz/last-use").is_file()


def test_unknown_workspace(client: TestClient) -> None:
    assert client.get("/espaces/nope").status_code == 404


def test_close_refuses_then_forces(
    client: TestClient, repository: Path, monkeypatch: Any
) -> None:
    _create(client, monkeypatch)
    path = repository.parent / "repo--demo"
    (path / "notes.md").write_text("x", encoding="utf8")

    refused = client.post("/espaces/demo/fermer", headers=ORIGIN)
    assert "Fermer quand même" in refused.text
    assert "notes.md" in refused.text
    assert path.is_dir()

    closed = client.post("/espaces/demo/fermer", data={"force": "true"}, headers=ORIGIN)
    assert "Fermé." in closed.text
    assert not path.exists()


def test_close_says_what_becomes_of_the_builds(
    repository: Path, monkeypatch: Any
) -> None:
    from studioz.app import create_app

    from deckz.stamps import write_stamp

    (repository / ".gitignore").write_text("/.run/\n/built/\n", encoding="utf8")
    (repository / "deckz.yml").write_text("worktree:\n  seed: [built]\n", "utf8")
    for args in (("add", "-A"), ("commit", "-qm", "Seed the builds")):
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@e",
                *args,
            ],
            check=True,
        )
    write_stamp(_write(repository / "built" / "fig.svg", "main's"), "old")
    client = TestClient(create_app(repository), base_url="http://localhost:8421")
    _create(client, monkeypatch)
    path = repository.parent / "repo--demo"
    write_stamp(_write(path / "built" / "fig.svg", "rebuilt"), "new")
    write_stamp(_write(path / "built" / "new.svg", "new"), "n")

    assert 'hx-get="/espaces/demo/fermer"' in client.get("/").text
    confirm = client.get("/espaces/demo/fermer").text
    assert "1 rendu (figures, vidéos) que le dossier principal n'a pas" in confirm
    assert "y sera recopié" in confirm
    assert "sera mis de côté" in confirm
    assert "built/fig.svg" in confirm
    assert path.is_dir()

    closed = client.post("/espaces/demo/fermer", headers=ORIGIN).text
    assert "Fermé." in closed
    assert "y a été recopié" in closed
    assert "a été mis de côté" in closed
    assert (repository / "built" / "new.svg").read_text(encoding="utf8") == "new"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")
    return path


def test_size(client: TestClient, monkeypatch: Any) -> None:
    _create(client, monkeypatch)

    assert client.get("/espaces/demo/taille").text.endswith(("o", "ko", "Mo"))


def test_size_ignores_hard_links(tmp_path: Path) -> None:
    from studioz.workspaces import size

    own = tmp_path / "own"
    own.write_bytes(b"x" * 100_000)
    cached = tmp_path / "cache" / "lib.so"
    cached.parent.mkdir()
    cached.write_bytes(b"x" * 1_000_000)
    (tmp_path / "linked.so").hardlink_to(cached)

    assert 100_000 <= size(tmp_path) < 200_000


def test_deck_tree() -> None:
    tree = deck_tree(
        [
            "decks/eni/cv3",
            "decks/orsys/INTRA/2026-10-fortinet",
            "decks/orsys/INTRA/2026-11-euronext",
            "decks/solo",
            "decks/solo/inner/sub",
        ]
    )

    # The folder every deck shares is left out; single folders are merged.
    assert tree.path == "decks"
    assert tree.decks == (("solo", "decks/solo"),)
    eni, orsys, solo = tree.folders
    assert eni == DeckFolder("eni", "decks/eni", (), (("cv3", "decks/eni/cv3"),))
    assert (orsys.name, orsys.path) == ("orsys/INTRA", "decks/orsys/INTRA")
    assert [name for name, _ in orsys.decks] == ["2026-10-fortinet", "2026-11-euronext"]
    # A deck holding decks is a folder too.
    assert (solo.name, solo.path) == ("solo", "decks/solo")
    assert solo.folders == (
        DeckFolder("inner", "decks/solo/inner", (), (("sub", "decks/solo/inner/sub"),)),
    )


def test_deck_tree_of_one_deck() -> None:
    tree = deck_tree(["client/abc"])

    assert tree == DeckFolder("", "client", (), (("abc", "client/abc"),))
