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

    missing = [SetupItem("pandoc", Status.MISSING, "install pandoc")]
    monkeypatch.setattr("studioz.workspaces.setup", lambda *_, **__: missing)

    response = client.post("/espaces", data={"name": "demo"}, headers=ORIGIN)

    assert "install pandoc" in response.text
    assert 'href="/espaces/demo"' in response.text


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
