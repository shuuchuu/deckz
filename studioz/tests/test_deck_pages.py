import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pytest import fixture
from studioz.app import create_app, watch_events
from studioz.watches import Watches

ORIGIN = {"Origin": "http://localhost:8421"}
DECK = "/espaces/demo/formations/client/abc"

# Stands for `deckz run --watch`: one build, then waits.
_FAKE_DECKZ = """
import pathlib, sys, time

pdf = pathlib.Path(sys.argv[1])
print("         INFO     Initial build", flush=True)
pdf.parent.mkdir(parents=True, exist_ok=True)
pdf.write_bytes(b"%PDF-1.4 built")
print("13:00:01 INFO     Initial build finished", flush=True)
try:
    time.sleep(60)
except KeyboardInterrupt:
    pass
"""


@fixture
def workspace(repository: Path, monkeypatch: Any) -> Path:
    monkeypatch.setattr("studioz.workspaces.setup", lambda *_, **__: [])
    client = TestClient(create_app(repository), base_url="http://localhost:8421")
    client.post("/espaces", data={"name": "demo"}, headers=ORIGIN)
    return repository.parent / "repo--demo"


def test_deck_page(client: TestClient, workspace: Path) -> None:
    page = client.get(DECK)

    assert page.status_code == 200
    assert f'data-events="{DECK}/evenements?lang=fr"' in page.text
    assert 'class="current"><a href="/espaces/demo/formations/client/abc"' in page.text
    assert 'href="?lang=en"' in page.text


def test_only_decks_of_the_workspace(client: TestClient, workspace: Path) -> None:
    (workspace / ".run" / "x").mkdir(parents=True)
    (workspace / ".run" / "x" / "deck.yml").write_text("name: x\n", encoding="utf8")

    for deck in ("client", ".run/x", "../repo/client/abc", "nope"):
        response = client.get(f"/espaces/demo/formations/{deck}")
        assert response.status_code == 404, deck


def test_pdf_once_built(client: TestClient, workspace: Path) -> None:
    assert client.get(f"{DECK}/pdf").status_code == 404
    pdf = workspace / "client" / "abc" / "pdf" / "en" / "abc-handout.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4")

    response = client.get(f"{DECK}/pdf?lang=en")

    assert response.content == b"%PDF-1.4"
    assert response.headers["content-type"] == "application/pdf"


def test_events_announce_the_build_and_its_pdf(
    repository: Path, workspace: Path, tmp_path: Path
) -> None:
    script = tmp_path / "fake_deckz.py"
    script.write_text(_FAKE_DECKZ, encoding="utf8")
    pdf = workspace / "client" / "abc" / "pdf" / "abc-handout.pdf"
    manager = Watches(lambda *_: [sys.executable, str(script), str(pdf)])
    watch = manager.watch(workspace, workspace / "client" / "abc", "fr")
    events: list[tuple[str, Any]] = []

    async def disconnected() -> bool:
        await asyncio.sleep(0)
        return any(name == "pdf" for name, _ in events)

    async def follow() -> None:
        async for event in watch_events(watch, "/x/pdf?lang=fr", disconnected):
            name, data = (line.split(": ", 1)[1] for line in event.split("\n")[:2])
            events.append((name, json.loads(data)))
            assert watch.clients == 1

    try:
        asyncio.run(asyncio.wait_for(follow(), 10))
    finally:
        manager.stop_all()

    assert ("state", {"state": "built", "errors": []}) in events
    assert events[-1] == ("pdf", {"url": f"/x/pdf?lang=fr&v={pdf.stat().st_mtime_ns}"})
    assert watch.clients == 0


def test_closing_studioz_stops_its_watches(
    repository: Path, workspace: Path, tmp_path: Path
) -> None:
    script = tmp_path / "fake_deckz.py"
    script.write_text(_FAKE_DECKZ, encoding="utf8")
    pdf = workspace / "client" / "abc" / "pdf" / "abc-handout.pdf"
    manager = Watches(lambda *_: [sys.executable, str(script), str(pdf)])

    with TestClient(create_app(repository, manager)):
        watch = manager.watch(workspace, workspace / "client" / "abc", "fr")

    assert not watch.alive()
