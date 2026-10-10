import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from time import sleep
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
)
from fastapi.testclient import TestClient
from pytest import raises
from studioz.agent import Agents
from studioz.app import Login, create_app

from studioz import asks

ORIGIN = {"Origin": "http://localhost:8421"}


def test_prompts() -> None:
    translate = asks.prompt(
        "traduire", {"changed": ["content/a/x.md"], "other": ["content/a/en/x.md"]}
    )
    assert "Porte-y la même modification" in translate
    assert "`content/a/en/x.md`" in translate
    fix = asks.prompt("corriger", {"refused": ["x.md: bad"], "path": ["x.md"]})
    assert "```\nx.md: bad\n```" in fix
    conflict = asks.prompt(
        "conflit", {"path": ["a.md", "b.md"], "upstream": ["origin/main"]}
    )
    assert "sur origin/main" in conflict
    assert "`a.md`, `b.md`" in conflict
    assert "Ne lance aucune commande git qui avance" in conflict
    with raises(ValueError, match="inconnue ou incomplète"):
        asks.prompt("publier", {})
    with raises(ValueError):
        asks.prompt("traduire", {"changed": ["a.md"]})


def test_the_draft_prompt_shows_the_change(workspace: Path) -> None:
    (workspace / "client" / "abc" / "deck.yml").write_text("name: x\n", "utf8")
    (workspace / "new.md").write_text("Nouveau\n", "utf8")
    text = asks.draft_prompt(workspace, ["client/abc/deck.yml", "new.md"])
    assert "-name: abc\n+name: x" in text
    assert "--- nouveau fichier new.md\nNouveau" in text
    assert "Initial" in text  # the last subjects, for the style


def test_draft_message_asks_without_tools(workspace: Path) -> None:
    seen: list[ClaudeAgentOptions] = []

    async def ask(_text: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        await asyncio.sleep(0)
        seen.append(options)
        yield AssistantMessage([TextBlock("Rename the deck")], "haiku")
        yield ResultMessage("success", 1, 1, False, 1, "s", result="Rename the deck")

    message = asyncio.run(asks.draft_message(workspace, ["new.md"], ask))
    assert message == "Rename the deck"
    assert seen[0].tools == []
    assert seen[0].max_turns == 1
    assert seen[0].model == "haiku"
    assert "ANTHROPIC_API_KEY" not in seen[0].env


def _client(repository: Path, **kwargs: Any) -> TestClient:
    app = create_app(repository, login=Login(check=lambda: (True, "a@b.fr")), **kwargs)
    return TestClient(app, base_url="http://localhost:8421")


def test_propose_a_commit_message(repository: Path, workspace: Path) -> None:
    (workspace / "a.md").write_text("A\n", "utf8")
    asked: list[list[str]] = []

    async def drafter(_workspace: Path, paths: list[str]) -> str:
        await asyncio.sleep(0)
        asked.append(paths)
        return "Add a"

    client = _client(repository, drafter=drafter)
    box = client.post(
        "/espaces/demo/commit/proposer",
        data={"path": "a.md", "listed": "a.md", "message": ""},
        headers=ORIGIN,
    ).text
    assert asked == [["a.md"]]
    assert ">Add a</textarea>" in box
    assert 'id="commit-message-box"' in box

    none = client.post(
        "/espaces/demo/commit/proposer",
        data={"listed": "a.md", "message": "Mine"},
        headers=ORIGIN,
    ).text
    assert "Cochez d&#39;abord les fichiers du commit." in none
    assert ">Mine</textarea>" in none


def test_a_failed_proposal_keeps_the_message(repository: Path, workspace: Path) -> None:
    (workspace / "a.md").write_text("A\n", "utf8")

    async def drafter(_workspace: Path, _paths: list[str]) -> str:
        await asyncio.sleep(0)
        msg = "usage limit"
        raise RuntimeError(msg)

    box = (
        _client(repository, drafter=drafter)
        .post(
            "/espaces/demo/commit/proposer",
            data={"path": "a.md", "listed": "a.md", "message": "Mine"},
            headers=ORIGIN,
        )
        .text
    )
    assert "Pas de proposition : usage limit" in box
    assert ">Mine</textarea>" in box


class _Recorder:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, options: ClaudeAgentOptions) -> "_Recorder":
        return self

    async def connect(self) -> None:
        pass

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)

    async def receive_response(self) -> AsyncIterator[Any]:
        yield ResultMessage("success", 1, 1, False, 1, "s")

    async def interrupt(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass


def test_a_dialog_asks_the_agent(repository: Path, workspace: Path) -> None:
    recorder = _Recorder()
    with _client(repository, agents=Agents(recorder)) as client:
        response = client.post(
            "/espaces/demo/agent/demander",
            data={"task": "conflit", "path": ["a.md"], "upstream": "origin/main"},
            headers=ORIGIN,
        )
        assert response.status_code == 204
        conversation = client.app.state.studio.agents.conversation(workspace)  # ty: ignore[unresolved-attribute]
        for _ in range(200):
            if not conversation.running:
                break
            sleep(0.01)
        unknown = client.post(
            "/espaces/demo/agent/demander", data={"task": "x"}, headers=ORIGIN
        )
    assert recorder.prompts[0].startswith("La mise à jour de l'espace sur origin/main")
    assert conversation.entries[0].kind == "person"
    assert unknown.status_code == 422
