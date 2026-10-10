import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from time import monotonic, sleep, time
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    RateLimitEvent,
    RateLimitInfo,
    ResultMessage,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from fastapi.testclient import TestClient
from pytest import fixture, mark, raises
from studioz.agent import (
    AGENT_DIR,
    OTHER,
    Agents,
    Choice,
    Conversation,
    Entry,
    asked,
    entries,
    refused_git,
)
from studioz.app import Login, create_app
from studioz.cli import login

from studioz import agent

ORIGIN = {"Origin": "http://localhost:8421"}
BASE = "/espaces/demo/agent"


@mark.parametrize(
    ("command", "refused"),
    [
        ("git status", None),
        ("git diff --stat && git log -3", None),
        ("git -C content show HEAD:a.md", None),
        ("git branch --show-current", None),
        ("git branch -a", None),
        ("git tag -l", None),
        ("git worktree list", None),
        ("uv run deckz check", None),
        ("git commit -m 'Ajoute un cadre'", "commit"),
        ("git add -A && git commit -m x", "commit"),
        ("git -C ../slides push origin main", "push"),
        ("git --no-pager reset --hard", "reset"),
        ("git checkout -- content/a.md", "checkout"),
        ("git switch main", "switch"),
        ("git stash", "stash"),
        ("git branch nouvelle", "branch"),
        ("git branch -D ws/demo", "branch"),
        ("git tag v1", "tag"),
        ("git worktree add ../x", "worktree"),
        ("ls; git rebase main", "rebase"),
    ],
)
def test_refused_git(command: str, refused: str | None) -> None:
    assert refused_git(command) == refused


def _assistant(*blocks: Any, parent: str | None = None) -> AssistantMessage:
    return AssistantMessage(list(blocks), "claude", parent_tool_use_id=parent)


def _result(
    session: str = "session-1", reason: str = "completed", **fields: Any
) -> ResultMessage:
    return ResultMessage(
        "success",
        2400,
        2000,
        fields.pop("is_error", False),
        1,
        session,
        terminal_reason=reason,
        **fields,
    )


def test_entries(tmp_path: Path) -> None:
    said = entries(
        tmp_path,
        _assistant(
            TextBlock("Je regarde la partie 2."),
            ToolUseBlock(
                "1",
                "Bash",
                {"command": f"ls {tmp_path}/content", "description": "Liste"},
            ),
            ToolUseBlock("2", "Edit", {"file_path": f"{tmp_path}/content/a.md"}),
            ToolUseBlock("3", "Grep", {"pattern": "Kafka"}),
            ToolUseBlock("4", "Mystery", {}),
        ),
    )
    assert [(e.kind, e.text, e.detail) for e in said] == [
        ("text", "Je regarde la partie 2.", ""),
        ("tool", "Liste", "ls content"),
        ("tool", "Modifie", "content/a.md"),
        ("tool", "Cherche", "Kafka"),
        ("tool", "Mystery", ""),
    ]
    assert (
        entries(tmp_path, _assistant(TextBlock("dans un sous-agent"), parent="1")) == []
    )

    failed = entries(
        tmp_path,
        UserMessage(
            [
                ToolResultBlock("1", "ok", is_error=False),
                ToolResultBlock("2", f"No such file: {tmp_path}/b.md", is_error=True),
                ToolResultBlock(
                    "3", "PreToolUse:Bash hook error: `git commit` est refusé", True
                ),
            ]
        ),
    )
    assert entries(tmp_path, UserMessage([ToolResultBlock("2", "x", True)]), True) == []
    assert [(e.text, e.detail) for e in failed] == [
        ("Refusé ou en échec", "No such file: b.md"),
        ("Refusé par studioz", "`git commit` est refusé"),
    ]

    assert entries(tmp_path, _result())[0].text == "Terminé en 2 s"
    assert entries(tmp_path, _result(reason="aborted_tools"))[0].text == (
        "Arrêté au bout de 2 s"
    )
    error = entries(tmp_path, _result(is_error=True, errors=["API 500"]))[0]
    assert (error.kind, error.detail) == ("error", "API 500")
    stopped = entries(tmp_path, _result(is_error=True, errors=["x"]), stopped=True)
    assert stopped[0].text == "Arrêté au bout de 2 s"

    limit = RateLimitEvent(RateLimitInfo("rejected", resets_at=None), "u", "s")
    assert entries(tmp_path, limit)[0].text == (
        "Limite d'utilisation de votre abonnement atteinte"
    )
    warning = RateLimitEvent(RateLimitInfo("allowed_warning"), "u", "s")
    assert entries(tmp_path, warning) == []


def test_the_hook_refuses_commits() -> None:
    def decision(command: str) -> Any:
        hook_input: Any = {"tool_name": "Bash", "tool_input": {"command": command}}
        return asyncio.run(agent._refuse_git(hook_input, None, {"signal": None}))

    assert decision("git status") == {}
    output = decision("git commit -am x")["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "`git commit` est refusé" in output["permissionDecisionReason"]


def test_other_permission_requests_are_denied() -> None:
    denied = asyncio.run(agent._deny("WebFetch", {}, ToolPermissionContext()))
    assert isinstance(denied, PermissionResultDeny)
    assert "studioz ne montre pas de demande" in denied.message


_QUESTIONS = {
    "questions": [
        {
            "question": "Quelle couleur ?",
            "header": "Couleur",
            "options": [
                {"label": "Rouge", "description": "La couleur rouge"},
                {"label": "Bleu", "description": "La couleur bleue"},
            ],
            "multiSelect": False,
        },
        {
            "question": "Quels fruits ?",
            "header": "Fruits",
            "options": [{"label": "Pomme"}, {"label": "Poire"}, {"label": "Kiwi"}],
            "multiSelect": True,
        },
    ]
}


def test_answers_as_claude_code_expects_them() -> None:
    color, fruits = asked(_QUESTIONS)
    assert color.choices[0] == Choice("Rouge", "La couleur rouge")
    assert color.answer(["Bleu"], "") == "Bleu"
    # A free answer counts once picked (typing it picks it, in the page).
    assert color.answer(["Bleu"], "Vert") == "Bleu"
    assert color.answer([OTHER], "Vert") == "Vert"
    assert color.answer([], "") == ""
    assert fruits.answer(["Kiwi", "Pomme"], "") == "Pomme, Kiwi"
    assert fruits.answer(["Poire"], " Mangue ") == "Poire, Mangue"
    assert asked({"questions": [{"header": "sans question"}, "?"]}) == []


def test_options(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-a-shell")
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    found = agent.options(tmp_path, "session-1")
    assert found.cwd == tmp_path
    assert found.resume == "session-1"
    assert found.setting_sources == ["project"]
    assert found.permission_mode == "auto"
    assert "ANTHROPIC_API_KEY" not in found.env
    assert found.env["PATH"].startswith(f"{tmp_path}/.venv/bin")
    assert found.env["UV_CACHE_DIR"] == f"{tmp_path}/.run/cache/uv"
    assert found.env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"


def _fake_cli(tmp_path: Path, status: dict[str, Any]) -> str:
    cli = tmp_path / "claude"
    cli.write_text(f"#!/bin/sh\necho '{json.dumps(status)}'\n", encoding="utf8")
    cli.chmod(0o755)
    return str(cli)


def test_logged_in(tmp_path: Path) -> None:
    status = {"loggedIn": True, "authMethod": "claude.ai", "email": "a@b.fr"}
    assert agent.logged_in(_fake_cli(tmp_path, status)) == (True, "a@b.fr")
    ok, why = agent.logged_in(_fake_cli(tmp_path, {"loggedIn": False}))
    assert not ok
    assert "aucun compte" in why
    ok, why = agent.logged_in(
        _fake_cli(tmp_path, {"loggedIn": True, "authMethod": "apiKey"})
    )
    assert not ok
    assert "apiKey" in why
    assert agent.logged_in(str(tmp_path / "missing"))[0] is False


Replies = Callable[[str], list[Any]]


class FakeClient:
    """Stands for `ClaudeSDKClient`: answers each prompt with `replies(prompt)`.

    A prompt `attends` makes it work until interrupted.
    """

    def __init__(self, options: ClaudeAgentOptions, replies: Replies) -> None:
        self.options = options
        self._replies = replies
        self.prompts: list[str] = []
        self.interrupted = False
        self.disconnected = False

    async def connect(self) -> None:
        if self.options.cwd and "panne" in str(self.options.cwd):
            msg = "Claude Code introuvable"
            raise RuntimeError(msg)

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)

    async def receive_response(self) -> AsyncIterator[Any]:
        if self.prompts[-1].endswith("écris"):
            cwd = Path(str(self.options.cwd))
            (cwd / "client" / "abc" / "deck.yml").write_text("name: x\n", "utf8")
            (cwd / "nouveau.md").write_text("nouveau\n", "utf8")
            yield _assistant(TextBlock("Écrit."))
            yield _result()
            return
        if self.prompts[-1] == "limite":
            yield RateLimitEvent(
                RateLimitInfo(
                    "rejected",
                    resets_at=int(time()) + 3600,
                    raw={"unifiedWindows": {"five_hour": {"utilization": 1.0}}},
                ),
                "u",
                "s",
            )
            yield _result(is_error=True, errors=["limit"])
            return
        if self.prompts[-1] == "demande":
            # As Claude Code asks: the tool use, then the permission request.
            yield _assistant(ToolUseBlock("q", agent.ASK, _QUESTIONS))
            assert self.options.can_use_tool is not None
            decision = await self.options.can_use_tool(
                agent.ASK, _QUESTIONS, ToolPermissionContext(tool_use_id="q")
            )
            if isinstance(decision, PermissionResultAllow):
                assert decision.updated_input is not None
                yield _assistant(
                    TextBlock(f"Reçu : {decision.updated_input['answers']}")
                )
            else:
                yield _assistant(TextBlock(f"Refusé : {decision.message}"))
            yield _result()
            return
        if self.prompts[-1] == "attends":
            while not self.interrupted:
                await asyncio.sleep(0.01)
            # As Claude Code ends an interrupted turn.
            yield _result(is_error=True, errors=["[ede_diagnostic] result_type=user"])
            return
        for message in self._replies(self.prompts[-1]):
            yield message

    async def interrupt(self) -> None:
        self.interrupted = True

    async def disconnect(self) -> None:
        self.disconnected = True


class FakeFactory:
    def __init__(self) -> None:
        self.clients: list[FakeClient] = []

    def __call__(self, options: ClaudeAgentOptions) -> FakeClient:
        def replies(prompt: str) -> list[Any]:
            return [
                _assistant(
                    TextBlock(f"Fait : {prompt}"),
                    ToolUseBlock("1", "Edit", {"file_path": "content/a.md"}),
                ),
                _result(session=f"session-{len(self.clients)}"),
            ]

        self.clients.append(FakeClient(options, replies))
        return self.clients[-1]


def _wait_idle(conversation: Conversation, timeout: float = 10) -> None:
    deadline = monotonic() + timeout
    while conversation.running:
        assert monotonic() < deadline, "the agent's turn never ended"
        sleep(0.02)


@fixture
def factory() -> FakeFactory:
    return FakeFactory()


@fixture
def logged_in() -> Login:
    return Login(check=lambda: (True, "a@b.fr"))


@fixture
def agent_client(
    workspace: Path, repository: Path, factory: FakeFactory, logged_in: Login
) -> Iterator[TestClient]:
    # As a context manager: the agent's turn runs in the app's event loop,
    # which must outlive the request starting it.
    app = create_app(repository, agents=Agents(factory), login=logged_in)
    with TestClient(app, base_url="http://localhost:8421") as client:
        yield client


def _conversation(client: TestClient, workspace: Path) -> Conversation:
    return client.app.state.studio.agents.conversation(workspace)  # ty: ignore[unresolved-attribute]


def test_the_pages_show_the_panel(agent_client: TestClient) -> None:
    page = agent_client.get("/espaces/demo").text
    assert 'id="agent"' in page
    assert f'data-events="{BASE}/evenements"' in page
    assert "/static/agent.js" in page


def test_a_turn_is_kept_and_resumed(
    agent_client: TestClient, workspace: Path, factory: FakeFactory
) -> None:
    response = agent_client.post(
        f"{BASE}/message", data={"message": "Relis\r\nla partie 2"}, headers=ORIGIN
    )
    assert response.status_code == 204
    conversation = _conversation(agent_client, workspace)
    _wait_idle(conversation)

    assert factory.clients[0].prompts == ["Relis\nla partie 2"]
    assert factory.clients[0].options.resume is None
    assert [(e.kind, e.text) for e in conversation.entries] == [
        ("person", "Relis\nla partie 2"),
        ("text", "Fait : Relis\nla partie 2"),
        ("tool", "Modifie"),
        ("end", "Terminé en 2 s"),
    ]
    assert conversation.session == "session-1"

    # studioz restarted: the transcript is back, the session resumed.
    again = Conversation(workspace, factory)
    assert again.entries == conversation.entries
    asyncio.run(_send_and_wait(again, "Et la partie 3"))
    assert factory.clients[1].options.resume == "session-1"
    assert again.entries[-1].text == "Terminé en 2 s"
    assert again.session == "session-2"


async def _send_and_wait(conversation: Conversation, prompt: str) -> None:
    assert await conversation.send(prompt)
    assert conversation._task is not None
    await conversation._task


def test_one_turn_at_a_time_and_stop(
    agent_client: TestClient, workspace: Path, factory: FakeFactory
) -> None:
    agent_client.post(f"{BASE}/message", data={"message": "attends"}, headers=ORIGIN)
    conversation = _conversation(agent_client, workspace)
    assert conversation.running

    busy = agent_client.post(
        f"{BASE}/message", data={"message": "autre chose"}, headers=ORIGIN
    )
    assert busy.status_code == 409
    assert busy.json() == {"error": "L'agent travaille encore"}

    stopped = agent_client.post(f"{BASE}/arreter", headers=ORIGIN)
    assert stopped.status_code == 204
    _wait_idle(conversation)
    assert conversation.entries[-1].text == "Arrêté au bout de 2 s"
    assert factory.clients[0].prompts == ["attends"]


def test_not_logged_in(workspace: Path, repository: Path, factory: FakeFactory) -> None:
    login = Login(check=lambda: (False, "Claude Code n'est connecté à aucun compte"))
    app = create_app(repository, agents=Agents(factory), login=login)
    with TestClient(app, base_url="http://localhost:8421") as client:
        response = client.post(
            f"{BASE}/message", data={"message": "Bonjour"}, headers=ORIGIN
        )
    assert response.status_code == 409
    assert "aucun compte" in response.json()["error"]
    assert not factory.clients


def test_messages_refused_from_another_site(
    agent_client: TestClient, factory: FakeFactory
) -> None:
    response = agent_client.post(
        f"{BASE}/message",
        data={"message": "git push"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert not factory.clients


def test_a_new_conversation_forgets_the_old_one(
    agent_client: TestClient, workspace: Path, factory: FakeFactory
) -> None:
    agent_client.post(f"{BASE}/message", data={"message": "Bonjour"}, headers=ORIGIN)
    conversation = _conversation(agent_client, workspace)
    _wait_idle(conversation)
    assert (workspace / AGENT_DIR / "transcript.jsonl").is_file()

    response = agent_client.post(f"{BASE}/nouvelle", headers=ORIGIN)

    assert response.status_code == 204
    assert conversation.entries == []
    assert conversation.session is None
    assert not (workspace / AGENT_DIR / "transcript.jsonl").exists()
    assert factory.clients[0].disconnected


def test_a_failing_agent_ends_its_turn(tmp_path: Path, factory: FakeFactory) -> None:
    conversation = Conversation(tmp_path / "panne", factory)
    asyncio.run(_send_and_wait(conversation, "Bonjour"))
    assert not conversation.running
    last = conversation.entries[-1]
    assert (last.kind, last.text, last.detail) == (
        "error",
        "L'agent s'est arrêté",
        "Claude Code introuvable",
    )


def test_an_idle_agent_is_stopped(
    tmp_path: Path, factory: FakeFactory, monkeypatch: Any
) -> None:
    conversation = Conversation(tmp_path, factory)

    async def scenario() -> None:
        await _send_and_wait(conversation, "Bonjour")
        await conversation.stop_if_idle()
        assert not factory.clients[0].disconnected
        monkeypatch.setattr(agent, "_IDLE_AFTER", -1)
        await conversation.stop_if_idle()

    asyncio.run(scenario())
    assert factory.clients[0].disconnected


def test_the_transcript_skips_damaged_lines(tmp_path: Path) -> None:
    directory = tmp_path / AGENT_DIR
    directory.mkdir(parents=True)
    kept = {"kind": "text", "text": "Bonjour", "detail": "", "at": "now"}
    (directory / "transcript.jsonl").write_text(
        f'{json.dumps(kept)}\n{{"kind": "text"\n{{"other": 1}}\n', encoding="utf8"
    )
    assert Conversation(tmp_path).entries == [Entry(**kept)]


def test_login_runs_claude_code(tmp_path: Path, monkeypatch: Any) -> None:
    called = tmp_path / "called"
    cli = tmp_path / "claude"
    cli.write_text(f'#!/bin/sh\necho "$@" > {called}\nexit 3\n', encoding="utf8")
    cli.chmod(0o755)
    monkeypatch.setattr(agent, "claude_cli", lambda: str(cli))

    with raises(SystemExit) as exited:
        login()

    assert exited.value.code == 3
    assert called.read_text(encoding="utf8") == "auth login --claudeai\n"


def _wait_question(conversation: Conversation, timeout: float = 10) -> int:
    deadline = monotonic() + timeout
    while conversation.question is None:
        assert monotonic() < deadline, "the agent never asked"
        sleep(0.02)
    return conversation.question.id


def test_the_agent_asks_and_waits_for_the_answer(
    agent_client: TestClient, workspace: Path
) -> None:
    agent_client.post(f"{BASE}/message", data={"message": "demande"}, headers=ORIGIN)
    conversation = _conversation(agent_client, workspace)
    question = _wait_question(conversation)
    assert conversation.running
    assert [e.kind for e in conversation.entries] == ["person", "question"]
    assert conversation.entries[-1].text == "Quelle couleur ?\nQuels fruits ?"

    def reply(**fields: Any) -> Any:
        return agent_client.post(f"{BASE}/reponse", data=fields, headers=ORIGIN)

    unanswered = reply(question=str(question), q0="Rouge")
    assert unanswered.status_code == 422
    assert unanswered.json() == {"error": "Pas de réponse à « Quels fruits ? »"}
    assert reply(question="999", q0="Rouge", q1="Kiwi").status_code == 409

    answered = reply(question=str(question), q0="Rouge", q1=["Kiwi", "Pomme"])
    assert answered.status_code == 204
    _wait_idle(conversation)

    answers = {"Quelle couleur ?": "Rouge", "Quels fruits ?": "Pomme, Kiwi"}
    assert [(e.kind, e.text) for e in conversation.entries][1:] == [
        ("question", "Quelle couleur ?\nQuels fruits ?"),
        ("person", "Quelle couleur ? → Rouge\nQuels fruits ? → Pomme, Kiwi"),
        ("text", f"Reçu : {answers}"),
        ("end", "Terminé en 2 s"),
    ]
    assert conversation.question is None
    assert reply(question=str(question), q0="Bleu", q1="Kiwi").status_code == 409


def test_stopping_drops_the_question(agent_client: TestClient, workspace: Path) -> None:
    agent_client.post(f"{BASE}/message", data={"message": "demande"}, headers=ORIGIN)
    conversation = _conversation(agent_client, workspace)
    _wait_question(conversation)

    agent_client.post(f"{BASE}/arreter", headers=ORIGIN)
    _wait_idle(conversation)

    assert conversation.question is None
    assert [e.text for e in conversation.entries][-2:] == [
        "Refusé : La personne a arrêté sans répondre.",
        "Arrêté au bout de 2 s",
    ]


def test_the_question_form(agent_client: TestClient, workspace: Path) -> None:
    from studioz.app import _agent_question

    agent_client.post(f"{BASE}/message", data={"message": "demande"}, headers=ORIGIN)
    conversation = _conversation(agent_client, workspace)
    _wait_question(conversation)
    form = _agent_question(conversation.question)
    assert f'name="question" value="{conversation.question.id}"' in form  # ty: ignore[unresolved-attribute]
    assert '<input type="radio" name="q0" value="Rouge">' in form
    assert '<input type="checkbox" name="q1" value="Kiwi">' in form
    assert f'<input type="radio" name="q0" value="{OTHER}">' in form
    assert 'name="q1-autre"' in form
    assert "La couleur rouge" in form
    agent_client.post(f"{BASE}/arreter", headers=ORIGIN)
    _wait_idle(conversation)


def test_the_agent_text_is_markdown_without_html() -> None:
    from studioz.app import _agent_entry

    html = _agent_entry(
        Entry(
            "text",
            "Tu veux **eni/ml5**.\n\n"
            "<script>alert(1)</script> [x](javascript:alert(1))",
        )
    )
    assert "<strong>eni/ml5</strong>" in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert 'href="javascript' not in html
    # Only the agent's text: the person's stays as typed.
    assert "**a**" in _agent_entry(Entry("person", "**a**"))


def test_static_files_are_checked_again(agent_client: TestClient) -> None:
    response = agent_client.get("/static/agent.js")
    assert response.headers["Cache-Control"] == "no-cache"
    again = agent_client.get(
        "/static/agent.js", headers={"If-None-Match": response.headers["ETag"]}
    )
    assert again.status_code == 304


def test_undo_the_last_turn(
    agent_client: TestClient, workspace: Path, factory: FakeFactory
) -> None:
    agent_client.post(f"{BASE}/message", data={"message": "écris"}, headers=ORIGIN)
    conversation = _conversation(agent_client, workspace)
    _wait_idle(conversation)
    assert [(e.kind, e.text, e.detail) for e in conversation.entries][-3:] == [
        ("text", "Écrit.", ""),
        (
            "changes",
            "2 fichiers modifiés par ce tour",
            "client/abc/deck.yml\nnouveau.md",
        ),
        ("end", "Terminé en 2 s", ""),
    ]

    response = agent_client.post(f"{BASE}/annuler", headers=ORIGIN)

    assert response.status_code == 204
    deck = workspace / "client" / "abc" / "deck.yml"
    assert deck.read_text(encoding="utf8") == "name: abc\n"
    assert not (workspace / "nouveau.md").exists()
    assert conversation.entries[-1].text == "Tour annulé : 2 fichier(s) remis"
    assert conversation.undoable is None
    again = agent_client.post(f"{BASE}/annuler", headers=ORIGIN)
    assert again.status_code == 409
    assert again.json() == {"error": "Aucun tour à annuler"}

    # The agent hears of it with the next message; the transcript shows
    # the person's own words.
    agent_client.post(f"{BASE}/message", data={"message": "Et ?"}, headers=ORIGIN)
    _wait_idle(conversation)
    told = factory.clients[0].prompts[-1]
    assert told.startswith("(La personne a annulé ton dernier tour")
    assert "client/abc/deck.yml, nouveau.md" in told
    assert told.endswith("\n\nEt ?")
    said = [e.text for e in conversation.entries if e.kind == "person"]
    assert said[-1] == "Et ?"


def test_the_last_turn_survives_a_restart(
    agent_client: TestClient, workspace: Path, factory: FakeFactory
) -> None:
    agent_client.post(f"{BASE}/message", data={"message": "écris"}, headers=ORIGIN)
    _wait_idle(_conversation(agent_client, workspace))
    again = Conversation(workspace, factory)
    assert again.undoable is not None
    assert asyncio.run(again.undo()) is None
    assert not (workspace / "nouveau.md").exists()


def test_usage_windows() -> None:
    info = RateLimitInfo(
        "allowed_warning",
        raw={
            "unifiedWindows": {
                "five_hour": {"utilization": 0.11, "resetsAt": time() + 600},
                "seven_day": {"utilization": 0.77, "resetsAt": time() + 3 * 86400},
            }
        },
    )
    found = agent.windows(info)
    assert [(w.name, w.used) for w in found] == [
        ("five_hour", 0.11),
        ("seven_day", 0.77),
    ]
    summary = agent.usage_summary(found)
    assert summary["text"] == "5 h : 11 % · 7 j : 77 %"
    assert summary["warn"] is True
    assert "77 % de la fenêtre de la semaine, renouvelée le " in str(summary["title"])
    assert agent.usage_summary(()) == {"text": "", "title": "", "warn": False}
    single = RateLimitInfo("allowed", rate_limit_type="five_hour", utilization=0.2)
    assert [(w.name, w.used) for w in agent.windows(single)] == [("five_hour", 0.2)]


def test_a_turn_says_its_usage(tmp_path: Path) -> None:
    end = entries(tmp_path, _result(total_cost_usd=0.094))[0]
    assert end.detail == (
        "Usage estimé : 0,09 $ au tarif de l'API, décompté de votre abonnement"
    )


def test_a_limit_pauses_then_resumes(tmp_path: Path, factory: FakeFactory) -> None:
    agents = Agents(factory)
    conversation = agents.conversation(tmp_path)

    async def scenario() -> None:
        await _send_and_wait(conversation, "limite")
        assert conversation.paused_until is not None
        assert agents.account.windows[0].used >= 1
        texts = [e.text for e in conversation.entries]
        assert texts[-3] == "Limite d'utilisation de votre abonnement atteinte"
        assert texts[-2] == "Interrompu par la limite au bout de 2 s"
        assert texts[-1].startswith("En pause : l'agent reprendra seul ")

        await agents.stop_idle()  # not due yet
        assert factory.clients[0].prompts == ["limite"]

        conversation.paused_until = time() - 1
        await agents.stop_idle()
        assert conversation._task is not None
        await conversation._task
        assert factory.clients[0].prompts[-1] == agent.RESUME
        assert conversation.paused_until is None
        assert "Reprise après la limite d'utilisation" in [
            e.text for e in conversation.entries
        ]

    asyncio.run(scenario())


def test_a_pause_is_cancelled(tmp_path: Path, factory: FakeFactory) -> None:
    conversation = Conversation(tmp_path, factory)

    async def scenario() -> None:
        await _send_and_wait(conversation, "limite")
        await conversation.interrupt()
        assert conversation.paused_until is None
        assert conversation.entries[-1].text == "Reprise annulée"
        await _send_and_wait(conversation, "limite")
        assert conversation.paused_until is not None
        # A message from the person takes over.
        await _send_and_wait(conversation, "Bonjour")
        assert conversation.paused_until is None

    asyncio.run(scenario())
