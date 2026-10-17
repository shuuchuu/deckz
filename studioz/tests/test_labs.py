import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pytest import fixture

ORIGIN = {"Origin": "http://localhost:8421"}
BASE = "/espaces/demo"
LAB = "labs/notebooks/nlp/embeddings"

# The workspace's own deckz: the real one.
_DECKZ = f"""#!{sys.executable}
import sys

from deckz.cli import main

main(sys.argv[1:])
"""


def _notebook(*cells: dict[str, Any]) -> str:
    return json.dumps({"cells": list(cells), "metadata": {}, "nbformat": 4})


def _markdown(source: str, id_: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {"id": id_}, "source": source}


def _code(source: str, id_: str, text: str = "") -> dict[str, Any]:
    outputs = [{"output_type": "stream", "name": "stdout", "text": text}]
    return {
        "cell_type": "code",
        "metadata": {"id": id_},
        "source": source,
        "outputs": outputs if text else [],
        "execution_count": 1 if text else None,
    }


_DEMO = _notebook(
    _markdown("# Plongements\n\nUn vecteur $v_i$ par mot.", "a"),
    _code("print('bonjour')", "b", "bonjour\n"),
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@fixture
def lab(workspace: Path, repository: Path) -> Path:
    (repository / ".git" / "info" / "exclude").write_text(".venv/\n", encoding="utf8")
    deckz = workspace / ".venv" / "bin" / "deckz"
    deckz.parent.mkdir(parents=True)
    deckz.write_text(_DECKZ, encoding="utf8")
    deckz.chmod(0o755)
    directory = workspace / LAB
    directory.mkdir(parents=True)
    (directory / "demo-fr.ipynb").write_text(_DEMO, encoding="utf8")
    (directory / "demo-en.ipynb").write_text(_DEMO, encoding="utf8")
    (directory / "hands-on-fr.ipynb").write_text(_notebook(), encoding="utf8")
    _git(workspace, "add", "labs")
    _git(workspace, "commit", "-m", "Add a lab")
    return directory


def test_the_view_lists_each_lab_by_kind(lab: Path, client: TestClient) -> None:
    view = client.get(f"{BASE}/tp").text

    assert 'data-lab="nlp/embeddings"' in view
    assert f'href="{BASE}/tp/nlp/embeddings/demo"' in view
    assert ">démo</a>" in view
    assert "TP <small>fr</small>" in view  # no English hands-on
    assert '<span class="count" title="Les notebooks modifiés' in view
    assert ">0</span>" in view

    (lab / "demo-en.ipynb").write_text(_notebook(), encoding="utf8")
    changed = client.get(f"{BASE}/tp?tp=nlp/embeddings/demo").text
    assert ">1</span>" in changed
    assert 'class="lab-kind current changed"' in changed


def test_the_page_shows_the_notebook_in_a_sandboxed_frame(
    lab: Path, client: TestClient
) -> None:
    page = client.get(f"{BASE}/tp/nlp/embeddings/demo")
    assert page.status_code == 200
    assert f'hx-get="{BASE}/tp/nlp/embeddings/demo/apercu?lang=fr"' in page.text

    view = client.get(f"{BASE}/tp/nlp/embeddings/demo/apercu", params={"lang": "en"})
    assert 'sandbox="allow-scripts allow-popups' in view.text
    assert f'src="{BASE}/tp/nlp/embeddings/demo/rendu?lang=en&v=' in view.text
    assert "fr manquant" not in view.text

    frame = client.get(f"{BASE}/tp/nlp/embeddings/demo/rendu", params={"lang": "en"})
    assert frame.headers["Content-Security-Policy"].startswith("sandbox allow-scripts")
    assert r"Un vecteur \(v_i\) par mot." in frame.text
    assert '<pre class="output stdout">bonjour\n</pre>' in frame.text
    assert '<span class="nb">print</span>' in frame.text


def test_a_missing_language_shows_the_other(lab: Path, client: TestClient) -> None:
    view = client.get(
        f"{BASE}/tp/nlp/embeddings/hands-on/apercu", params={"lang": "en"}
    )

    assert "en manquant" in view.text
    assert "affiché en fr" in view.text
    assert client.get(f"{BASE}/tp/nlp/missing/demo").status_code == 200
    assert client.get(f"{BASE}/tp/nlp/missing/demo/apercu").status_code == 404


def test_the_changes_cell_by_cell(lab: Path, client: TestClient) -> None:
    url = f"{BASE}/tp/nlp/embeddings/demo/apercu"
    unchanged = client.get(url, params={"vue": "avant-apres"}).text
    assert "n'a pas changé depuis le dernier commit" in unchanged
    assert "<iframe" not in unchanged

    (lab / "demo-fr.ipynb").write_text(
        _notebook(
            _markdown("# Plongements\n\nUn vecteur $v_i$ par mot.", "a"),
            _code("print('salut')", "b", "salut\n"),
            _markdown("Fin.", "c"),
        ),
        encoding="utf8",
    )
    view = client.get(url, params={"vue": "avant-apres"}).text
    assert "modifié" in view
    assert "<iframe" in view

    frame = client.get(
        f"{BASE}/tp/nlp/embeddings/demo/rendu", params={"vue": "avant-apres"}
    ).text
    assert "1 cellule inchangée" in frame
    assert frame.count('class="change changed"') == 1
    assert frame.count('class="change added"') == 1
    assert '<span class="line del">' in frame
    assert "salut" in frame


def test_a_new_notebook_is_all_added(lab: Path, client: TestClient) -> None:
    (lab / "hands-on-en.ipynb").write_text(_DEMO, encoding="utf8")

    view = client.get(
        f"{BASE}/tp/nlp/embeddings/hands-on/apercu",
        params={"lang": "en", "vue": "avant-apres"},
    ).text
    frame = client.get(
        f"{BASE}/tp/nlp/embeddings/hands-on/rendu",
        params={"lang": "en", "vue": "avant-apres"},
    ).text

    assert ">nouveau</span>" in view
    assert "Nouveau notebook" in frame
    assert frame.count('class="change added"') == 2


def test_open_in_my_editor(lab: Path, client: TestClient, monkeypatch: Any) -> None:
    opened = []
    monkeypatch.setattr(
        "studioz.labs.open_in_editor", lambda path: opened.append(path) or None
    )

    response = client.post(
        f"{BASE}/tp/nlp/embeddings/demo/ouvrir", params={"lang": "en"}, headers=ORIGIN
    )

    assert opened == [lab / "demo-en.ipynb"]
    assert "ouvert" in response.text
