import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic, sleep

from fastapi.testclient import TestClient
from pytest import fixture
from studioz.jobs import JobState

ORIGIN = {"Origin": "http://localhost:8421"}
BASE = "/espaces/demo"
LAB = "labs/notebooks/nlp/embeddings"

# The workspace's own deckz: the real one, but for a pass, which here holds
# its machine (a `state.json`, as deckz keeps it) until it's stopped, then
# destroys it, as `deckz labs gpu pass` does.
_DECKZ = f"""#!{sys.executable}
import json, signal, sys, time
from datetime import datetime
from pathlib import Path

args = sys.argv[1:]
if args[:3] == ["labs", "gpu", "pass"] and "--dry-run" not in args:
    state = Path(".run/gpu/main/state.json")

    def stop(*_):
        state.unlink(missing_ok=True)
        print("Instance 100 destroyed: nothing is billed", flush=True)
        sys.exit(130)

    signal.signal(signal.SIGINT, stop)
    state.parent.mkdir(parents=True, exist_ok=True)
    rented_at = datetime.now().astimezone().isoformat(timespec="seconds")
    state.write_text(json.dumps({{
        "id": 100, "gpu": "Tesla T4", "machine": 42, "price": 0.16,
        "rented_at": rented_at,
    }}))
    print("pass " + " ".join(args[3:]), flush=True)
    time.sleep(30)
    stop()

from deckz.cli import main

main(args)
"""

# Vast.ai's CLI: one offer, and each destruction logged.
_VASTAI = """#!/bin/sh
case "$1 $2" in
  "search offers")
    echo '[{"id": 7, "gpu_name": "Tesla T4", "machine_id": 42,
            "dph_total": 0.16, "geolocation": "FR"}]' ;;
  "destroy instance") echo "$3" >> .run/destroyed ;;
esac
"""

_SHORT: dict[str, object] = {
    "cell_type": "code",
    "metadata": {},
    "source": "SHORT_RUN = False",
    "outputs": [],
    "execution_count": None,
}


def _notebook(*cells: dict[str, object]) -> str:
    return json.dumps({"cells": list(cells), "metadata": {}, "nbformat": 4})


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _script(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf8")
    path.chmod(0o755)


@fixture
def lab(workspace: Path, repository: Path) -> Path:
    (repository / ".git" / "info" / "exclude").write_text(".venv/\n", encoding="utf8")
    bin_dir = workspace / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    _script(bin_dir / "deckz", _DECKZ)
    _script(bin_dir / "vastai", _VASTAI)
    (workspace / ".run").mkdir(exist_ok=True)
    directory = workspace / LAB
    directory.mkdir(parents=True)
    (directory / "demo-fr.ipynb").write_text(_notebook(_SHORT), encoding="utf8")
    (directory / "demo-en.ipynb").write_text(_notebook(_SHORT), encoding="utf8")
    (directory / "hands-on-fr.ipynb").write_text(_notebook(_SHORT), encoding="utf8")
    _git(workspace, "add", "labs")
    _git(workspace, "commit", "-m", "Add a lab")
    return directory


def _form(client: TestClient, data: dict[str, object]) -> str:
    response = client.post(f"{BASE}/gpu/formulaire", data=data, headers=ORIGIN)
    assert response.status_code == 200
    return response.text


def _rent_button(page: str) -> str:
    found = re.search(r'<button type="button" id="gpu-rent".*?</button>', page, re.S)
    return " ".join(found[0].split()) if found else ""


def test_the_modal_gives_the_offer_and_the_ceiling(
    lab: Path, client: TestClient
) -> None:
    page = _form(client, {"tp": "nlp/embeddings/demo"})

    # Both languages, ticked; outputs kept, since it's a full run of demos.
    assert page.count('name="carnet"') == 2
    assert f'value="{LAB}/demo-fr.ipynb" checked' in page
    assert 'name="sorties" value="1" checked' in page
    assert "Tesla T4, 0,16 $/h" in page
    assert "jamais exécuté ainsi" in page
    # No estimate: deckz's 4 h ceiling, and the button says the most it costs.
    assert 'name="plafond" value="4"' in page
    assert "au plus 0,64 $" in _rent_button(page)
    assert "Louer une Tesla T4 et exécuter" in _rent_button(page)
    # Enter in a field estimates again; the focus is on Annuler.
    assert 'hx-trigger="change, submit"' in page
    assert re.search(r"<button[^>]* autofocus [^>]*>Annuler</button>", page)


def test_the_estimate_comes_from_the_last_runs(
    lab: Path, repository: Path, client: TestClient
) -> None:
    # The workspace has no notes of its own: the main checkout's.
    notes = repository / ".run" / "gpu" / "main" / "notes.md"
    notes.parent.mkdir(parents=True)
    notes.write_text(
        "Noted 2026-10-01 10:00 CEST:\n"
        "#### nlp__embeddings__demo-fr.full.ipynb: exit 0, 1200 s, peak RAM 1 GiB\n"
        "#### nlp__embeddings__demo-en.full.ipynb: exit 0, 600 s, peak RAM 1 GiB\n",
        encoding="utf8",
    )

    page = _form(client, {"tp": "nlp/embeddings/demo"})

    assert "dernière exécution : 20 min" in page
    # 10 min to rent and boot, 30 to run: 40 min; twice that, rounded up.
    assert "40 min, soit ≈ 0,11 $" in page
    assert 'name="plafond" value="1.5"' in page
    assert "(≈ 0,11 $)" in _rent_button(page)


def test_the_modal_follows_the_choices(lab: Path, client: TestClient) -> None:
    candidates = [f"{LAB}/demo-fr.ipynb", f"{LAB}/demo-en.ipynb"]
    page = _form(
        client,
        {
            "candidat": candidates,
            "carnet": [candidates[1]],
            "mode": "court",
            "sorties": "1",
            "sorties_vu": "1",
            "plafond": "1.5",
            "plafond_auto": "4",
        },
    )

    # The French one unticked stays offered; a short run keeps no outputs.
    assert f'value="{candidates[0]}">' in page
    assert f'value="{candidates[1]}" checked' in page
    assert 'name="sorties" value="1" disabled' in page
    assert 'name="plafond" value="1.5"' in page

    page = _form(client, {"tp": ["nlp/embeddings/hands-on"]})
    assert 'name="sorties" value="1" disabled' in page
    assert "un TP n'en enregistre pas" in page


def test_the_modal_says_what_deckz_refuses(
    lab: Path, workspace: Path, client: TestClient
) -> None:
    (workspace / LAB / "demo-fr.ipynb").write_text(_notebook(), encoding="utf8")

    page = _form(client, {"tp": "nlp/embeddings/demo", "mode": "court"})

    assert "deckz refuse cette exécution" in page
    assert "SHORT_RUN" in page
    assert not _rent_button(page)


def _wait(predicate: object, timeout: float = 20) -> None:
    deadline = monotonic() + timeout
    while not predicate():  # ty: ignore[call-non-callable]
        assert monotonic() < deadline
        sleep(0.05)


def test_a_pass_runs_as_a_job_and_is_stopped_after_a_question(
    lab: Path, workspace: Path, client: TestClient
) -> None:
    jobs = client.app.state.studio.jobs  # ty: ignore[unresolved-attribute]
    # A build running doesn't hold the pass back: lanes.
    build = jobs.submit(
        workspace, "build", [[sys.executable, "-c", "import time; time.sleep(30)"]]
    )
    page = client.post(
        f"{BASE}/gpu/lancer",
        data={
            "carnet": [f"{LAB}/demo-fr.ipynb", f"{LAB}/demo-en.ipynb"],
            "mode": "complet",
            "sorties": "1",
            "sorties_vu": "1",
            "plafond": "2",
        },
        headers=ORIGIN,
    ).text
    assert "data-job-started" in page
    job = jobs.jobs(workspace)[0]
    assert job.lane == "gpu"
    assert job.steps[0][1:] == (
        "labs",
        "gpu",
        "pass",
        f"{LAB}/demo-fr.ipynb",
        f"{LAB}/demo-en.ipynb",
        "--no-short",
        "--write-outputs",
        "--max-hours",
        "2",
        "--machine",
        "main",
    )
    assert job.link == (
        "Voir l'avant/après",
        f"{BASE}/tp/nlp/embeddings/demo?lang=fr&vue=avant-apres",
    )
    state = workspace / ".run" / "gpu" / "main" / "state.json"
    _wait(state.is_file)
    assert build.state is JobState.RUNNING

    badge = client.get(f"{BASE}/gpu/resume").text
    assert "GPU Tesla T4 · 0 min · 0,00 $" in badge

    # The modal won't start another meanwhile.
    page = _form(client, {"tp": "nlp/embeddings/demo"})
    assert "déjà en cours dans cet espace" in page
    assert not _rent_button(page)

    # Stopping it asks first: its runs in progress would be lost.
    page = client.post(f"{BASE}/gpu/arreter", headers=ORIGIN).text
    assert "seront perdues" in page
    assert not job.finished
    page = client.post(
        f"{BASE}/gpu/arreter", data={"confirme": "1"}, headers=ORIGIN
    ).text
    assert "Arrêt demandé" in page
    _wait(lambda: job.finished)

    assert job.state is JobState.STOPPED
    assert "Instance 100 destroyed: nothing is billed" in job.log
    assert not state.exists()
    assert client.get(f"{BASE}/gpu/resume").text.strip() == ""
    jobs.stop(workspace, build.id)


def test_a_machine_no_pass_runs_is_destroyed_at_once(
    lab: Path, workspace: Path, client: TestClient
) -> None:
    # As a crash leaves it: rented, its pass gone.
    state = workspace / ".run" / "gpu" / "main" / "state.json"
    state.parent.mkdir(parents=True)
    rented_at = datetime.now().astimezone() - timedelta(minutes=90)
    state.write_text(
        json.dumps(
            {
                "id": 123,
                "gpu": "RTX_A4000",
                "machine": 42,
                "price": 0.2,
                "rented_at": rented_at.isoformat(timespec="seconds"),
            }
        ),
        encoding="utf8",
    )

    badge = client.get(f"{BASE}/gpu/resume").text
    assert "GPU RTX_A4000 · 1 h 30 · 0,30 $" in badge
    page = client.post(f"{BASE}/gpu/machines", headers=ORIGIN).text
    assert "Aucune exécution de studioz ne l'utilise" in page

    page = client.post(f"{BASE}/gpu/arreter", data={"machine": "main"}, headers=ORIGIN)
    assert "data-job-started" in page.text
    jobs = client.app.state.studio.jobs  # ty: ignore[unresolved-attribute]
    job = jobs.jobs(workspace)[0]
    _wait(lambda: job.finished)

    assert job.state is JobState.DONE, list(job.log)
    assert (workspace / ".run" / "destroyed").read_text() == "123\n"
    assert not state.exists()
    assert client.get(f"{BASE}/gpu/resume").text.strip() == ""


def test_a_pass_job_is_stopped_from_the_dialog(
    lab: Path, workspace: Path, client: TestClient
) -> None:
    jobs = client.app.state.studio.jobs  # ty: ignore[unresolved-attribute]
    client.post(
        f"{BASE}/gpu/lancer",
        data={"carnet": [f"{LAB}/demo-fr.ipynb"], "mode": "court", "plafond": "1"},
        headers=ORIGIN,
    )
    job = jobs.jobs(workspace)[0]
    assert "--short" in job.steps[0]
    assert "--no-write-outputs" in job.steps[0]
    assert job.link is None
    _wait(lambda: job.state is JobState.RUNNING)

    page = client.get(f"{BASE}/taches/{job.id}").text

    # Its Arrêter opens the dialog asking first, not the plain stop.
    assert f'data-url="{BASE}/gpu/arreter">Arrêter…' in page
    assert f"/taches/{job.id}/arreter" not in page
    jobs.stop(workspace, job.id)
    _wait(lambda: job.finished)
