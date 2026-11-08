import json
import sys
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from fastapi.testclient import TestClient
from pytest import fixture
from studioz.app import create_app

ORIGIN = {"Origin": "http://localhost:8421"}
BASE = "/espaces/demo"


def _level(ok: bool | None, **more: Any) -> dict[str, Any]:
    return {"ok": ok, **more}


def _deck(deck: str, opens: dict[str, str] | None, **more: Any) -> dict[str, Any]:
    return {
        "deck": deck,
        "intra": False,
        "past": False,
        "next_session": None,
        "sessions": None,
        "frames": 0,
        "levels": {
            "content": _level(True, total=3, to_review=0, counts={"fresh": 3}),
            "labs": _level(None, total=0, to_review=0, counts={}),
            "pass": {"ok": False, "state": "none", "report": "r.md", "date": None},
            "dated_facts": _level(None, due=[], next_due_on=None),
            "findings": _level(False, open={"E": 1, "P": 2}, total=3, critical=1),
        },
        "course_notes": {"counts": {"missing": 1}, "share": 0.5, "error": None},
        "chapters_due": [{"rule": "supports/**", "why": "une règle", "count": 2}],
        "opens": opens,
        **more,
    }


def _section(section: str, *, care: bool, opens: dict[str, str] | None) -> dict:
    return {
        "section": section,
        "state": "stale" if care else "fresh",
        "score": 12 if care else 0,
        "frames": 4,
        "decks": ["decks/client/abc"],
        "counts": {"fresh": 1, "stale": 1 if care else 0},
        "reports": [],
        "findings": _level(None, open={"E": 0}, total=0, critical=0, reports=[]),
        "dated_facts": _level(None, due=[], reports=[]),
        "needs_care": care,
        "opens": opens,
    }


DASHBOARD = {
    "today": "2026-11-08",
    "sessions": {"available": False, "why": "pas de calendrier"},
    "totals": {
        "sections": {"fresh": 1, "stale": 1},
        "files": {"fresh": 3, "stale": 1},
        "findings": {
            "open": {"E": 1, "P": 2},
            "critical": 1,
            "done": 0,
            "refused": 0,
            "none": 0,
            "reports_with_open": 1,
        },
        "course_notes": {"counts": {}, "share": 0.5, "complete_decks": 0},
        "rules": [],
        "dated_facts_due": [],
    },
    "decks": [
        _deck(
            "decks/client/abc",
            {"file": "supports/sec/a.md", "why": "chapter_due"},
            next_session={
                "start": "2026-11-20",
                "end": "2026-11-21",
                "days": 2,
                "tentative": True,
                "intra": False,
                "calendar": "Alex",
            },
        ),
        _deck("decks/client/two", None),
    ],
    "left_out": ["decks/client/INTRA/2026-01-old"],
    "sections": [
        _section("sec", care=True, opens={"file": "docs/qa/sec.md", "why": "report"}),
        _section("calm", care=False, opens=None),
    ],
    "problems": [],
}


def _fake(workspace: Path, *, fails: bool = False) -> Path:
    """The workspace's deckz printing `DASHBOARD`, each call written down.

    Returns:
        The file listing its calls.
    """
    calls = workspace.parent / "calls.txt"
    deckz = workspace / ".venv" / "bin" / "deckz"
    deckz.parent.mkdir(parents=True, exist_ok=True)
    out = (
        "sys.stderr.write('Error: no review.dir\\n'); sys.exit(1)"
        if fails
        else f"print({json.dumps(json.dumps(DASHBOARD))})"
    )
    deckz.write_text(
        f"#!{sys.executable}\nimport sys\n"
        f"open({str(calls)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n{out}\n",
        encoding="utf8",
    )
    deckz.chmod(0o755)
    return calls


def _wait(client: TestClient, workspace: Path) -> None:
    studio = client.app.state.studio  # pyrefly: ignore[missing-attribute]
    deadline = monotonic() + 20
    while studio.dashboards.state(workspace).running:
        assert monotonic() < deadline
        sleep(0.05)


@fixture
def app_client(repository: Path) -> TestClient:
    return TestClient(create_app(repository), base_url="http://localhost:8421")


def test_nothing_runs_the_dashboard_by_itself(
    workspace: Path, app_client: TestClient
) -> None:
    calls = _fake(workspace)

    page = app_client.get(f"{BASE}/maintenance")
    assert page.status_code == 200
    assert f'hx-get="{BASE}/maintenance/tableau"' in page.text
    assert 'id="editor-pane"' in page.text
    assert "Maintenance : calculer le tableau de bord" in page.text
    board = app_client.get(f"{BASE}/maintenance/tableau").text
    assert "Pas encore calculé" in board
    assert "every 2s" not in board
    (workspace / "client" / "abc" / "deck.yml").write_text("name: x\n", "utf8")
    app_client.get(f"{BASE}/maintenance/tableau")
    assert "Pas encore calculé" in app_client.get(f"{BASE}/maintenance/resume").text
    # Every workspace page has the view, which runs nothing either.
    assert f'hx-get="{BASE}/maintenance/resume"' in app_client.get(BASE).text
    assert not calls.exists()


def test_the_button_runs_it_and_the_result_stays(
    workspace: Path, repository: Path, app_client: TestClient
) -> None:
    calls = _fake(workspace)

    started = app_client.post(f"{BASE}/maintenance/calculer", headers=ORIGIN)
    assert started.status_code == 204
    assert started.headers["HX-Trigger"] == "maintenance-changed"
    _wait(app_client, workspace)
    assert calls.read_text(encoding="utf8") == "dashboard --json\n"

    board = app_client.get(f"{BASE}/maintenance/tableau").text
    assert "Calculé à l&#39;instant" in board
    assert "Recalculer" in board
    # The decks in deckz's order, the folder they share not repeated.
    assert board.index(">abc</a>") < board.index(">two</a>")
    assert "20/11 ?" in board
    # The label of the session's calendar, when several are read.
    assert '<small class="calendar" title="Agenda">Alex</small>' in board
    assert '<tr data-file="supports/sec/a.md">' in board
    assert ">chapitre dû</a>" in board
    # A deck with nothing to open links to its page.
    assert f'<a href="{BASE}/formations/decks/client/two" title="Ni chapitre' in board
    assert "3 [1]" in board
    assert "1 formation INTRA passée non affichée" in board
    # Only the sections needing care.
    assert '<tr data-file="docs/qa/sec.md">' in board
    assert "calm" not in board
    assert "sans le calendrier : pas de calendrier" in board
    summary = app_client.get(f"{BASE}/maintenance/resume").text
    assert "1 section à soigner" in summary
    assert "Prochaine session : abc, 20/11 (Alex)" in summary

    # It outlives studioz.
    again = TestClient(create_app(repository), base_url="http://localhost:8421")
    assert ">two</a>" in again.get(f"{BASE}/maintenance/tableau").text
    assert calls.read_text(encoding="utf8") == "dashboard --json\n"


def test_a_failed_run_says_why_and_keeps_the_last_result(
    workspace: Path, app_client: TestClient
) -> None:
    _fake(workspace)
    app_client.post(f"{BASE}/maintenance/calculer", headers=ORIGIN)
    _wait(app_client, workspace)
    _fake(workspace, fails=True)
    app_client.post(f"{BASE}/maintenance/calculer", headers=ORIGIN)
    _wait(app_client, workspace)

    board = app_client.get(f"{BASE}/maintenance/tableau").text
    assert "Le calcul a échoué : Error: no review.dir" in board
    assert ">two</a>" in board
