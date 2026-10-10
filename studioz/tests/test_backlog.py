import json
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage
from fastapi.testclient import TestClient
from studioz.agent import Agents
from studioz.app import Login, create_app
from studioz.backlog import Backlog, Stale, catching_up

from studioz import asks

ORIGIN = {"Origin": "http://localhost:8421"}

_STALE = {
    "stale": [
        {
            "path": "content/a/a.md",
            "sibling": "content/a/en/a.md",
            "since": "abc123",
            "commits": [
                {"sha": "1", "subject": "Fix a"},
                {"sha": "2", "subject": "Extend a"},
            ],
        }
    ]
}


def _backlog(tmp_path: Path, found: dict[str, Any] = _STALE) -> Backlog:
    script = tmp_path / "fake_stale.py"
    script.write_text(
        f"import sys\nprint({json.dumps(json.dumps(found))})\nsys.exit(1)\n",
        encoding="utf8",
    )
    return Backlog(lambda _: [sys.executable, str(script)])


def _finished(backlog: Backlog, workspace: Path) -> tuple[Stale, ...]:
    deadline = monotonic() + 10
    while (report := backlog.report(workspace)).running:
        assert monotonic() < deadline, "timed out"
        sleep(0.05)
    assert report.error is None
    return report.result or ()


def test_the_backlog(tmp_path: Path, workspace: Path) -> None:
    found = _finished(_backlog(tmp_path), workspace)
    assert found == (
        Stale("content/a/a.md", "content/a/en/a.md", "abc123", ("Fix a", "Extend a")),
    )


def test_catching_up() -> None:
    stale = Stale("content/a/a.md", "content/a/en/a.md", None, ("x",))
    assert catching_up(["content/a/en/a.md"], (stale,)) == [stale]
    assert catching_up(["content/a/en/a.md", "content/b/b.md"], (stale,)) == []
    assert catching_up(["content/a/a.md"], (stale,)) == []
    assert catching_up([], (stale,)) == []


def test_the_catch_up_prompt() -> None:
    text = asks.prompt(
        "rattraper",
        {
            "changed": ["content/a/a.md"],
            "other": ["content/a/en/a.md"],
            "since": ["abc123"],
            "subject": ["Fix a", "Extend a"],
        },
    )
    assert "n'a pas suivis :\n- Fix a\n- Extend a" in text
    assert "`git diff abc123..HEAD -- content/a/a.md`" in text
    never = asks.prompt(
        "rattraper",
        {"changed": ["content/a/a.md"], "other": ["content/a/en/a.md"], "since": [""]},
    )
    assert "`git log -p -- content/a/a.md`" in never


class _Recorder:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, _options: ClaudeAgentOptions) -> "_Recorder":
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


def test_the_panel_and_its_button(
    tmp_path: Path, repository: Path, workspace: Path
) -> None:
    backlog = _backlog(tmp_path)
    recorder = _Recorder()
    app = create_app(
        repository,
        backlog=backlog,
        agents=Agents(recorder),
        login=Login(check=lambda: (True, "a@b.fr")),
    )
    with TestClient(app, base_url="http://localhost:8421") as client:
        assert 'hx-get="/espaces/demo/traductions"' in client.get("/espaces/demo").text
        _finished(backlog, workspace)
        panel = client.get("/espaces/demo/traductions").text
        assert 'À traduire <span class="count">1</span>' in panel
        assert "→ content/a/en/a.md, 2 commits" in panel
        assert 'data-agent-task="rattraper"' in panel
        # As the button posts its values.
        sent = client.post(
            "/espaces/demo/agent/demander",
            data={
                "task": "rattraper",
                "changed": "content/a/a.md",
                "other": "content/a/en/a.md",
                "since": "abc123",
                "subject": ["Fix a", "Extend a"],
            },
            headers=ORIGIN,
        )
        assert sent.status_code == 204
        conversation = client.app.state.studio.agents.conversation(workspace)  # ty: ignore[unresolved-attribute]
        deadline = monotonic() + 10
        while conversation.running:
            assert monotonic() < deadline
            sleep(0.02)
    assert recorder.prompts[0].startswith("`content/a/a.md` a changé")


def test_an_empty_backlog_shows_nothing(
    tmp_path: Path, repository: Path, workspace: Path
) -> None:
    backlog = _backlog(tmp_path, {"stale": []})
    client = TestClient(
        create_app(repository, backlog=backlog), base_url="http://localhost:8421"
    )
    _finished(backlog, workspace)
    assert "<h2>" not in client.get("/espaces/demo/traductions").text


def test_a_catch_up_commit_is_preset(
    tmp_path: Path, repository: Path, workspace: Path
) -> None:
    for path, text in (("content/a/a.md", "fr"), ("content/a/en/a.md", "en")):
        (workspace / path).parent.mkdir(parents=True, exist_ok=True)
        (workspace / path).write_text(text, encoding="utf8")
    git = ["git", "-C", str(workspace), "-c", "user.name=t", "-c", "user.email=t@e"]
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "Add a", "--no-verify"], check=True)
    (workspace / "content/a/en/a.md").write_text("en, porté", encoding="utf8")
    backlog = _backlog(tmp_path)
    client = TestClient(
        create_app(repository, backlog=backlog), base_url="http://localhost:8421"
    )
    _finished(backlog, workspace)
    dialog = client.post(
        "/espaces/demo/commit/formulaire",
        data={"listed": "content/a/en/a.md", "path": "content/a/en/a.md"},
        headers=ORIGIN,
    ).text
    assert 'name="lang_sync" value="only" checked' in dialog
    assert "portage de content/a/a.md" in dialog
