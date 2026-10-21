import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage
from fastapi.testclient import TestClient
from pytest import fixture
from studioz.agent import Agents, Conversation
from studioz.app import Login, create_app

from studioz import workflows, workspaces

ORIGIN = {"Origin": "http://localhost:8421"}

_DECLARED = """\
schema_version: 1
studioz:
  workflows:
    - name: { fr: Nouvelle formation, en: New training }
      description: { fr: À partir d'un programme. }
      skill: nouvelle-formation
      inputs:
        - { name: program, kind: file, label: { fr: Programme }, accept: ".pdf,.md" }
        - { name: notes, kind: long-text, label: Remarques, required: false }
      prompt: "Crée la formation à partir du programme {program}. {notes}"
    - name: Relire la formation (QA)
      skill: qa-formation
      scope: deck
      prompt: "Fais le QA de {deck}."
      model: opus
"""


def _declare(
    workspace: Path, yaml: str = _DECLARED, skills: tuple[str, ...] = ()
) -> None:
    (workspace / "deckz.yml").write_text(yaml, encoding="utf8")
    for skill in skills:
        directory = workspace / ".claude" / "skills" / skill
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(f"---\nname: {skill}\n---\n", "utf8")


def test_declared_workflows(tmp_path: Path) -> None:
    assert workflows.declared(tmp_path) == workflows.Declared()
    _declare(tmp_path, skills=("nouvelle-formation",))
    found = workflows.declared(tmp_path)
    assert found.error is None
    assert [w.key for w in found.workflows] == [
        "nouvelle-formation",
        "relire-la-formation-qa",
    ]
    assert found.missing == {"relire-la-formation-qa": "qa-formation"}
    assert [w.key for w in found.scoped("deck")] == ["relire-la-formation-qa"]
    new = found.workflows[0]
    assert new.title == "Nouvelle formation"
    assert new.preview() == (
        "Crée la formation à partir du programme [Programme]. [Remarques]"
    )
    prompt, shown = new.message({"program": ".run/studioz/fichiers/p.pdf"})
    assert prompt == (
        "Suis la skill `nouvelle-formation` du dépôt pour cette demande.\n\n"
        "Crée la formation à partir du programme .run/studioz/fichiers/p.pdf."
    )
    assert shown.startswith("Nouvelle formation : Crée la formation")


def test_a_repository_without_workflows(tmp_path: Path) -> None:
    (tmp_path / "deckz.yml").write_text("{}\n", encoding="utf8")
    assert workflows.declared(tmp_path) == workflows.Declared()


def _error(tmp_path: Path, section: str) -> str:
    (tmp_path / "deckz.yml").write_text(f"studioz:\n{section}", encoding="utf8")
    error = workflows.declared(tmp_path).error
    assert error is not None
    return error


def test_invalid_declarations_say_what_is_wrong(tmp_path: Path) -> None:
    def one(fields: str) -> str:
        return _error(tmp_path, f"  workflows:\n    - {{{fields}}}\n")

    assert "workflows.0.then" in one("name: a, skill: s, prompt: p, then: x")
    assert "le {x} du prompt n'est aucun champ" in one(
        "name: a, skill: s, prompt: '{x}'"
    )
    assert "`{deck}` demande `scope: deck`" in one(
        "name: a, skill: s, prompt: '{deck}'"
    )
    assert "une accolade s'écrit deux fois" in one("name: a, skill: s, prompt: '{'")
    assert "skill" in one("name: a, skill: '../x', prompt: p")
    assert "workflows.0.model" in one("name: a, skill: s, prompt: p, model: 'Opus 5'")
    assert "deux workflows s'appellent « a »" in _error(
        tmp_path,
        "  workflows:\n"
        "    - {name: A, skill: s, prompt: p}\n"
        "    - {name: a, skill: t, prompt: q}\n",
    )
    assert "studioz.workflow" in _error(tmp_path, "  workflow: []\n")


def test_files_are_kept_once(tmp_path: Path) -> None:
    first = workflows.keep_file(tmp_path, "../Programme 2026?.pdf", b"a")
    assert first == ".run/studioz/fichiers/Programme 2026_.pdf"
    assert workflows.keep_file(tmp_path, "Programme 2026?.pdf", b"a") == first
    other = workflows.keep_file(tmp_path, "Programme 2026?.pdf", b"b")
    assert other == ".run/studioz/fichiers/Programme 2026_-2.pdf"
    assert (tmp_path / other).read_bytes() == b"b"
    assert workflows.keep_file(tmp_path, "...", b"c").endswith("/fichier")


class _Recorder:
    """Stands for `ClaudeSDKClient`: records the prompts, ends each turn."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.models: list[str | None] = []
        """The model of each Claude Code started, then of each change."""

    def __call__(self, options: ClaudeAgentOptions) -> "_Recorder":
        self.models.append(options.model)
        return self

    async def connect(self) -> None:
        pass

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)

    async def set_model(self, model: str | None = None) -> None:
        self.models.append(model)

    async def receive_response(self) -> AsyncIterator[Any]:
        yield ResultMessage("success", 1, 1, False, 1, "s")

    async def interrupt(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass


@fixture
def recorder() -> _Recorder:
    return _Recorder()


@fixture
def studio(
    repository: Path, workspace: Path, recorder: _Recorder
) -> Iterator[TestClient]:
    _declare(workspace, skills=("nouvelle-formation", "qa-formation"))
    app = create_app(
        repository,
        agents=Agents(recorder),
        login=Login(check=lambda: (True, "a@b.fr")),
    )
    # As a context manager: the agent's turn runs in the app's event loop.
    with TestClient(app, base_url="http://localhost:8421") as client:
        yield client


def _conversation(client: TestClient, workspace: Path) -> Conversation:
    return client.app.state.studio.agents.conversation(workspace)  # ty: ignore[unresolved-attribute]


def _wait_idle(conversation: Conversation) -> None:
    deadline = monotonic() + 10
    while conversation.running:
        assert monotonic() < deadline, "the agent's turn never ended"
        sleep(0.02)


def test_the_pages_offer_the_workflows(studio: TestClient) -> None:
    page = studio.get("/espaces/demo").text
    assert "Nouvelle formation</button>" in page
    assert "Relire la formation (QA)…</button>" in page
    assert "/espaces/demo/workflows/nouvelle-formation/formulaire" in page
    deck = studio.get("/espaces/demo/formations/client/abc").text
    # The sidebar's "Avec l'agent" view, about the deck on screen.
    assert '"formation": "client/abc"' in deck
    listed = studio.post(
        "/espaces/demo/workflows", data={"formation": "client/abc"}, headers=ORIGIN
    ).text
    # The deck's own first, about the deck on screen.
    assert listed.index("Relire la formation") < listed.index("Nouvelle formation")
    assert '"formation": "client/abc"' in listed


def test_a_deck_without_workflows_has_none(repository: Path, workspace: Path) -> None:
    client = TestClient(create_app(repository), base_url="http://localhost:8421")
    assert "aucun workflow" in client.get("/espaces/demo/formations/client/abc").text
    assert "aucun workflow" in client.get("/espaces/demo").text


def test_the_forms(studio: TestClient) -> None:
    form = studio.post(
        "/espaces/demo/workflows/nouvelle-formation/formulaire", headers=ORIGIN
    ).text
    assert 'type="file" name="program" accept=".pdf,.md" required' in form
    assert '<textarea name="notes" rows="4">' in form
    assert "la skill <code>nouvelle-formation</code>" in form
    chosen = studio.post(
        "/espaces/demo/workflows/relire-la-formation-qa/formulaire", headers=ORIGIN
    ).text
    assert '<option value="client/abc">client/abc</option>' in chosen
    fixed = studio.post(
        "/espaces/demo/workflows/relire-la-formation-qa/formulaire",
        data={"formation": "client/abc"},
        headers=ORIGIN,
    ).text
    assert '<input type="hidden" name="deck" value="client/abc">' in fixed
    assert "<blockquote>Fais le QA de client/abc.</blockquote>" in fixed
    assert "<select" not in fixed
    assert (
        studio.post("/espaces/demo/workflows/x/formulaire", headers=ORIGIN).status_code
        == 404
    )


def test_a_workflow_starts_a_turn(
    studio: TestClient, workspace: Path, recorder: _Recorder
) -> None:
    response = studio.post(
        "/espaces/demo/workflows/nouvelle-formation",
        data={"notes": "Deux jours.\r\nINTRA."},
        files={"program": ("programme.pdf", b"%PDF", "application/pdf")},
        headers=ORIGIN,
    )
    assert response.status_code == 200
    assert response.headers["HX-Trigger"] == "agent-started"
    conversation = _conversation(studio, workspace)
    _wait_idle(conversation)
    assert recorder.prompts == [
        "Suis la skill `nouvelle-formation` du dépôt pour cette demande.\n\n"
        "Crée la formation à partir du programme "
        ".run/studioz/fichiers/programme.pdf. Deux jours.\nINTRA."
    ]
    assert (workspace / ".run/studioz/fichiers/programme.pdf").read_bytes() == b"%PDF"
    assert conversation.entries[0].kind == "person"
    assert conversation.entries[0].text.startswith("Nouvelle formation : Crée")
    assert recorder.models == ["sonnet"]

    # With the conversation going on, the form offers a fresh one.
    form = studio.post(
        "/espaces/demo/workflows/relire-la-formation-qa/formulaire", headers=ORIGIN
    ).text
    assert 'name="nouvelle"' in form
    studio.post(
        "/espaces/demo/workflows/relire-la-formation-qa",
        data={"deck": "client/abc", "nouvelle": "1"},
        headers=ORIGIN,
    )
    _wait_idle(conversation)
    assert recorder.prompts[-1].endswith("Fais le QA de client/abc.")
    assert conversation.entries[0].text == (
        "Relire la formation (QA) : Fais le QA de client/abc."
    )
    # The QA declares its model; the person's next message is on studioz's.
    assert recorder.models == ["sonnet", "opus"]
    studio.post(
        "/espaces/demo/agent/message", data={"message": "Merci"}, headers=ORIGIN
    )
    _wait_idle(conversation)
    assert recorder.models == ["sonnet", "opus", "sonnet"]


def test_a_workflow_refuses_what_is_missing(
    studio: TestClient, workspace: Path, recorder: _Recorder
) -> None:
    def start(key: str, **kwargs: Any) -> str:
        return studio.post(
            f"/espaces/demo/workflows/{key}", headers=ORIGIN, **kwargs
        ).text

    no_file = start("nouvelle-formation", data={"notes": "Gardées"})
    assert "Remplissez « Programme »." in no_file
    assert ">Gardées</textarea>" in no_file
    assert "Choisissez la formation." in start(
        "relire-la-formation-qa", data={"deck": "../x"}
    )
    (workspace / ".claude/skills/qa-formation/SKILL.md").unlink()
    missing = start("relire-la-formation-qa", data={"deck": "client/abc"})
    assert "La skill « qa-formation » n&#39;existe pas dans cet espace." in missing
    assert recorder.prompts == []


def test_a_workflow_needs_the_login(repository: Path, workspace: Path) -> None:
    _declare(workspace, skills=("nouvelle-formation", "qa-formation"))
    app = create_app(
        repository,
        agents=Agents(_Recorder()),
        login=Login(check=lambda: (False, "Claude Code n'est connecté à aucun compte")),
    )
    client = TestClient(app, base_url="http://localhost:8421")
    refused = client.post(
        "/espaces/demo/workflows/relire-la-formation-qa",
        data={"deck": "client/abc"},
        headers=ORIGIN,
    ).text
    assert "connecté à aucun compte" in refused


def test_an_invalid_section_shows(studio: TestClient, workspace: Path) -> None:
    (workspace / "deckz.yml").write_text("studioz: {workflow: []}\n", "utf8")
    page = studio.get("/espaces/demo").text
    assert "Les workflows de l&#39;espace sont illisibles" in page
    assert "studioz.workflow" in page


def _commit_declaration(repository: Path) -> None:
    _declare(repository, skills=("nouvelle-formation", "qa-formation"))
    for args in (("add", "-A"), ("commit", "-qm", "Workflows")):
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


def test_the_workflows_of_a_commit(repository: Path) -> None:
    assert workflows.declared_at(repository) == workflows.Declared()
    _commit_declaration(repository)
    # The checkout's own edits don't count: a workspace starts from the commit.
    (repository / "deckz.yml").write_text("studioz: {workflow: []}\n", "utf8")
    (repository / ".claude/skills/qa-formation/SKILL.md").unlink()
    found = workflows.declared_at(repository)
    assert found.error is None
    assert found.missing == {}
    assert [w.key for w in found.workflows] == [
        "nouvelle-formation",
        "relire-la-formation-qa",
    ]
    assert workflows.decks_at(repository) == ["client/abc"]
    assert workflows.declared_at(repository, "HEAD~1") == workflows.Declared()


def test_free_names(repository: Path, workspace: Path) -> None:
    assert workspace.name == "repo--demo"
    assert workspaces.free_name(repository, "demo") == "demo-2"
    assert workspaces.free_name(repository, "QA de x/y !") == "QA-de-x-y"
    assert workspaces.free_name(repository, "///") == "travail"


@fixture
def home(
    repository: Path, recorder: _Recorder, monkeypatch: Any
) -> Iterator[TestClient]:
    _commit_declaration(repository)
    monkeypatch.setattr("studioz.workspaces.setup", lambda *_, **__: [])
    app = create_app(
        repository,
        agents=Agents(recorder),
        login=Login(check=lambda: (True, "a@b.fr")),
    )
    with TestClient(app, base_url="http://localhost:8421") as client:
        yield client


def test_the_home_page_offers_the_workflows(home: TestClient) -> None:
    page = home.get("/").text
    assert "Commencer avec l'agent" in page
    assert 'data-url="/workflows/nouvelle-formation/formulaire"' in page
    assert 'id="action-dialog"' in page
    form = home.post(
        "/workflows/relire-la-formation-qa/formulaire", headers=ORIGIN
    ).text
    assert 'hx-post="/workflows/relire-la-formation-qa"' in form
    assert 'name="espace"' in form
    assert '<option value="client/abc">client/abc</option>' in form
    assert "créé à partir de main (" in form


def test_a_workflow_opens_a_workspace(
    home: TestClient, repository: Path, recorder: _Recorder
) -> None:
    response = home.post(
        "/workflows/relire-la-formation-qa",
        data={"deck": "client/abc"},
        headers=ORIGIN,
    )
    assert (
        response.headers["HX-Redirect"] == "/espaces/abc/formations/client/abc?agent=1"
    )
    created = repository.parent / "repo--abc"
    conversation = _conversation(home, created)
    _wait_idle(conversation)
    assert recorder.prompts[-1].endswith("Fais le QA de client/abc.")

    # Named by the person, with a file kept in the new workspace.
    named = home.post(
        "/workflows/nouvelle-formation",
        data={"espace": "pandas"},
        files={"program": ("p.md", b"# P", "text/markdown")},
        headers=ORIGIN,
    )
    assert named.headers["HX-Redirect"] == "/espaces/pandas?agent=1"
    assert (repository.parent / "repo--pandas/.run/studioz/fichiers/p.md").is_file()
    _wait_idle(_conversation(home, repository.parent / "repo--pandas"))
    assert "programme .run/studioz/fichiers/p.md" in recorder.prompts[-1]


def test_a_workflow_needs_its_answers_before_the_workspace(
    home: TestClient, repository: Path, recorder: _Recorder
) -> None:
    refused = home.post(
        "/workflows/nouvelle-formation", data={"espace": "x"}, headers=ORIGIN
    ).text
    assert "Remplissez « Programme »." in refused
    assert 'name="espace" value="x"' in refused
    assert not (repository.parent / "repo--x").exists()
    taken = home.post(
        "/workflows/relire-la-formation-qa",
        data={"deck": "client/abc", "espace": "../x"},
        headers=ORIGIN,
    ).text
    assert "invalid worktree name" in taken
    assert recorder.prompts == []


def test_a_workflow_waits_for_the_installation(
    home: TestClient, monkeypatch: Any, recorder: _Recorder
) -> None:
    from deckz.setting_up import SetupItem, Status

    missing = [SetupItem("pandoc", Status.MISSING, "install pandoc")]
    monkeypatch.setattr("studioz.workspaces.setup", lambda *_, **__: missing)
    shown = home.post(
        "/workflows/relire-la-formation-qa", data={"deck": "client/abc"}, headers=ORIGIN
    ).text
    assert "install pandoc" in shown
    assert "n'a donc pas commencé" in shown
    assert recorder.prompts == []


_WITH_REPORT = """\
studioz:
  workflows:
    - name: Relire la formation (QA)
      skill: qa-formation
      scope: deck
      prompt: "Fais le QA de {deck}."
      report: true
      then:
        name: Appliquer les corrections
        skill: qa-fix
        prompt: "Corrige dans {deck} :\\n{chosen}\\nRapport : {report}"
"""

_REPORT = """\
# QA de client/abc

## Erreurs

- [ ] `a.md`, cadre « X » : faux.
  Remplacer par Y.
- [ ] `b.md` : coquille.

## Incohérences

Rien de grave.

* [x] `c.md` : deux noms.
"""


def test_then_needs_a_report(tmp_path: Path) -> None:
    def one(fields: str) -> str:
        return _error(tmp_path, f"  workflows:\n    - {{{fields}}}\n")

    assert "`then` demande `report: true`" in one(
        "name: a, skill: s, prompt: p, then: {name: b, skill: t, prompt: q}"
    )
    assert "le {deck} du prompt de `then` n'est aucun champ ({chosen}, {report})" in (
        one(
            "name: a, skill: s, prompt: p, report: true,"
            " then: {name: b, skill: t, prompt: '{deck}'}"
        )
    )


def test_checklists(tmp_path: Path) -> None:
    parts = workflows.checklist(_REPORT)
    assert [(p.title, p.notes) for p in parts] == [
        ("QA de client/abc", ""),
        ("Erreurs", ""),
        ("Incohérences", "Rien de grave."),
    ]
    items = [item for part in parts for item in part.items]
    assert [(i.index, i.checked, i.text) for i in items] == [
        (0, False, "`a.md`, cadre « X » : faux.\nRemplacer par Y."),
        (1, False, "`b.md` : coquille."),
        (2, True, "`c.md` : deux noms."),
    ]
    path = tmp_path / "r.md"
    path.write_text(_REPORT, encoding="utf8")
    workflows.tick(path, {1})
    ticked = path.read_text(encoding="utf8")
    assert "- [x] `b.md`" in ticked
    assert "* [ ] `c.md`" in ticked
    assert ticked.replace("[x]", "[ ]") == _REPORT.replace("[x]", "[ ]")


@fixture
def reporting(
    repository: Path, workspace: Path, recorder: _Recorder
) -> Iterator[TestClient]:
    _declare(workspace, _WITH_REPORT, skills=("qa-formation", "qa-fix"))
    app = create_app(
        repository,
        agents=Agents(recorder),
        login=Login(check=lambda: (True, "a@b.fr")),
    )
    with TestClient(app, base_url="http://localhost:8421") as client:
        yield client


def test_a_report_then_its_follow_up(
    reporting: TestClient, workspace: Path, recorder: _Recorder
) -> None:
    report = workspace / ".run/studioz/rapports/relire-la-formation-qa--client-abc.md"
    report.parent.mkdir(parents=True)
    report.write_text("ancien\n", encoding="utf8")
    reporting.post(
        "/espaces/demo/workflows/relire-la-formation-qa",
        data={"deck": "client/abc"},
        headers=ORIGIN,
    )
    conversation = _conversation(reporting, workspace)
    _wait_idle(conversation)
    assert not report.exists()  # the previous run's is gone
    assert recorder.prompts[-1].endswith(
        "écris aussi tes constats dans "
        "`.run/studioz/rapports/relire-la-formation-qa--client-abc.md` (même si la "
        "méthode suivie ne modifie aucun fichier par ailleurs), pour que la personne "
        "y choisisse ceux à traiter : un titre `## ` par catégorie, puis un constat "
        "par case à cocher (`- [ ] …`), chacun compréhensible seul (fichier, cadre ou "
        "cellule, le problème, ce que tu proposes), en Markdown, sans rien d'autre "
        "que de courtes remarques sous les titres."
    )
    panel = reporting.get("/espaces/demo/rapports").text
    assert "Relire la formation (QA)</button>" in panel
    assert "pas encore écrit" in panel
    waiting = reporting.post(
        "/espaces/demo/rapports/relire-la-formation-qa--client-abc", headers=ORIGIN
    ).text
    assert "L'agent n'a pas encore écrit ce rapport" in waiting

    # The agent wrote it.
    report.write_text(_REPORT, encoding="utf8")
    assert "1/3 cochés" in reporting.get("/espaces/demo/rapports").text
    base = "/espaces/demo/rapports/relire-la-formation-qa--client-abc"
    dialog = reporting.post(base, headers=ORIGIN).text
    assert '<input type="checkbox" name="item" value="2" checked>' in dialog
    assert "Appliquer les corrections</button>" in dialog
    assert reporting.post(f"{base}/coches", data={"item": ["0"]}, headers=ORIGIN)
    assert "- [x] `a.md`" in report.read_text(encoding="utf8")
    assert "* [ ] `c.md`" in report.read_text(encoding="utf8")

    none = reporting.post(f"{base}/suite", headers=ORIGIN).text
    assert "Cochez au moins un constat." in none
    sent = reporting.post(f"{base}/suite", data={"item": ["0", "1"]}, headers=ORIGIN)
    assert sent.headers["HX-Trigger"] == "agent-started"
    _wait_idle(conversation)
    assert recorder.prompts[-1] == (
        "Suis la skill `qa-fix` du dépôt pour cette demande.\n\n"
        "Corrige dans client/abc :\n"
        "- `a.md`, cadre « X » : faux.\n  Remplacer par Y.\n"
        "- `b.md` : coquille.\n"
        "Rapport : .run/studioz/rapports/relire-la-formation-qa--client-abc.md"
    )
    assert conversation.entries[-2].text.startswith("Appliquer les corrections : ")


def test_no_reports_no_panel(studio: TestClient) -> None:
    assert "<h2>Rapports" not in studio.get("/espaces/demo/rapports").text
    assert 'hx-get="/espaces/demo/rapports"' in studio.get("/espaces/demo").text


def test_the_palette_s_commands(studio: TestClient) -> None:
    deck = studio.get("/espaces/demo/formations/client/abc").text
    commands = deck.split('<div id="commands" hidden>')[1].split("</div>")[0]

    # Each command is a button the page's own handlers know.
    assert (
        'data-url="/espaces/demo/formations/client/abc/construire/formulaire"'
        in commands
    )
    assert "Formation : passer en en" in commands
    assert 'data-open-panel="construction"' in commands
    assert "Workflow : Relire la formation (QA)…" in commands
    assert '"formation": "client/abc"' in commands
    page = studio.get("/espaces/demo").text
    workspace = page.split('<div id="commands" hidden>')[1].split("</div>")[0]
    assert "Formation :" not in workspace
    assert "Workflow : Nouvelle formation…" in workspace
    assert 'id="palette"' in page
