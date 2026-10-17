import json
import sys
from pathlib import Path
from time import monotonic, sleep

from fastapi.testclient import TestClient
from pytest import fixture
from studioz.jobs import Job, Jobs, JobState

ORIGIN = {"Origin": "http://localhost:8421"}
DECK = "/espaces/demo/formations/client/abc"

# Stands for the workspace's own deckz: prints its arguments, and for
# `upload --dry-run --json` the deck's PDFs, `old.pdf` being outdated.
_FAKE_DECKZ = """#!/bin/sh
if [ "$1 $2" = "upload --dry-run" ]; then
    echo '{"pdfs": ["client/abc/pdf/abc-handout.pdf", "client/abc/pdf/old.pdf"],'
    if [ -f old.flag ]; then echo '"outdated": ["client/abc/pdf/old.pdf"]}'
    else echo '"outdated": []}'; fi
    exit 0
fi
echo "deckz $* in $(basename "$PWD")"
"""


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def _wait(job: Job, timeout: float = 10) -> None:
    deadline = monotonic() + timeout
    while not job.finished:
        assert monotonic() < deadline, f"job {job.title} never finished"
        sleep(0.02)


def test_a_workspace_runs_its_jobs_one_after_the_other(tmp_path: Path) -> None:
    jobs = Jobs()
    marker = tmp_path / "marker"
    first = jobs.submit(
        tmp_path,
        "first",
        [
            _python(
                "import time, pathlib; time.sleep(0.3); "
                f"pathlib.Path({str(marker)!r}).touch()"
            )
        ],
    )
    second = jobs.submit(
        tmp_path,
        "second",
        [_python(f"import pathlib; print(pathlib.Path({str(marker)!r}).exists())")],
    )
    assert second.state is JobState.QUEUED
    other = jobs.submit(tmp_path / "other", "other", [_python("print('in parallel')")])
    _wait(other)
    assert first.state is JobState.RUNNING

    _wait(second)

    assert first.state is JobState.DONE
    assert list(second.log)[-1] == "True"
    assert [job.title for job in jobs.jobs(tmp_path)] == ["second", "first"]


def test_a_failing_step_stops_the_job(tmp_path: Path) -> None:
    jobs = Jobs()
    job = jobs.submit(
        tmp_path,
        "steps",
        [
            _python("print('one')"),
            _python("raise SystemExit(3)"),
            _python("print('three')"),
        ],
    )
    _wait(job)
    assert job.state is JobState.FAILED
    log = "\n".join(job.log)
    assert "one" in log
    assert "(code de sortie 3)" in log
    assert "three" not in log


def test_the_log_drops_where_deckz_logged_each_line(tmp_path: Path) -> None:
    jobs = Jobs()
    lines = [
        "12:00:00 INFO     Building it      _presentation.py:395",
        f"See {tmp_path}/content/a.md",
        "pipelines.py:180",
    ]
    job = jobs.submit(tmp_path, "log", [_python(f"print({chr(10).join(lines)!r})")])
    _wait(job)
    assert list(job.log)[1:] == ["12:00:00 INFO     Building it", "See content/a.md"]


def test_stop_a_running_job_and_a_queued_one(tmp_path: Path) -> None:
    jobs = Jobs()
    running = jobs.submit(
        tmp_path,
        "long",
        [_python("import time; print('started', flush=True); time.sleep(30)")],
    )
    queued = jobs.submit(tmp_path, "next", [_python("print('never')")])
    deadline = monotonic() + 10
    while "started" not in running.log:
        assert monotonic() < deadline
        sleep(0.02)

    jobs.stop(tmp_path, queued.id)
    jobs.stop(tmp_path, running.id)

    _wait(running)
    assert running.state is JobState.STOPPED
    assert queued.state is JobState.STOPPED
    assert "never" not in queued.log


@fixture
def fake_deckz(workspace: Path, repository: Path) -> Path:
    (repository / ".git" / "info" / "exclude").write_text(".venv/\n", encoding="utf8")
    deckz = workspace / ".venv" / "bin" / "deckz"
    deckz.parent.mkdir(parents=True)
    deckz.write_text(_FAKE_DECKZ, encoding="utf8")
    deckz.chmod(0o755)
    return deckz


def _job(client: TestClient, response_text: str) -> Job:
    # The job the response shows: the last one started.
    job = client.app.state.studio.jobs._jobs[-1]  # ty: ignore[unresolved-attribute]
    assert f'id="job-{job.id}"' in response_text
    _wait(job)
    return job


def test_build_a_deck_every_option_spelled_out(
    fake_deckz: Path, client: TestClient
) -> None:
    form = client.post(f"{DECK}/construire/formulaire", headers=ORIGIN).text
    assert 'value="handout" checked' in form
    assert 'value="html">' in form

    response = client.post(
        f"{DECK}/construire",
        data={"kind": ["handout", "print"], "lang": ["fr", "en"]},
        headers=ORIGIN,
    )

    # The page closes the dialog for the panel's Tâches tab.
    assert json.loads(response.headers["HX-Trigger-After-Settle"]) == {
        "jobs-changed": None,
        "job-started": None,
    }
    job = _job(client, response.text)
    assert job.state is JobState.DONE
    assert job.title == "Construire client/abc (fr, en : support, version à imprimer)"
    assert job.log[0] == (
        "$ .venv/bin/deckz run --handout --no-presentation --print "
        "--no-part-handouts --no-html --sync --lang fr en"
    )
    assert (
        "deckz run --handout --no-presentation --print --no-part-handouts "
        "--no-html --sync --lang fr en in abc"
    ) in job.log
    badge = client.get("/espaces/demo/taches/resume").text
    assert "Dernière tâche terminée" in badge
    listed = client.get("/espaces/demo/taches").text
    assert "--print --no-part-handouts" in listed
    # The job's last reload has the tab, and its count of jobs running, reload.
    ended = client.get(f"/espaces/demo/taches/{job.id}")
    assert ended.headers["HX-Trigger-After-Settle"] == "jobs-changed"
    assert '<span class="count" hidden>0</span>' in listed


def test_build_needs_a_language_and_a_document(
    fake_deckz: Path, client: TestClient
) -> None:
    page = client.post(
        f"{DECK}/construire",
        data={"kind": ["part-handouts"], "lang": "fr"},
        headers=ORIGIN,
    ).text
    assert "Choisissez au moins une langue" in page
    assert not client.app.state.studio.jobs._jobs  # ty: ignore[unresolved-attribute]


def test_upload_shows_the_pdfs_and_refuses_outdated_ones(
    fake_deckz: Path, workspace: Path, client: TestClient
) -> None:
    form = client.post(f"{DECK}/envoyer/formulaire", headers=ORIGIN).text
    assert "<code>client/abc/pdf/old.pdf</code>" in form
    assert "Envoyer 2 PDF</button>" in form

    (workspace / "client" / "abc" / "old.flag").touch()
    form = client.post(f"{DECK}/envoyer/formulaire", headers=ORIGIN).text
    assert "ne correspond plus au contenu" in form
    assert "disabled>Envoyer 2 PDF" in form

    job = _job(client, client.post(f"{DECK}/envoyer", headers=ORIGIN).text)
    assert "deckz upload in abc" in job.log


def test_publish(fake_deckz: Path, client: TestClient) -> None:
    form = client.post("/espaces/demo/publier/formulaire", headers=ORIGIN).text
    assert "Publier les TP" in form
    assert "<h3>Les TP</h3>" in form
    # It reloads itself until the workspace's first check is in.
    assert 'hx-trigger="every 2s"' in form
    assert "Publier les vidéos" in form

    refused = client.post(
        "/espaces/demo/publier", data={"what": "everything"}, headers=ORIGIN
    )
    assert refused.status_code == 422

    job = _job(
        client,
        client.post(
            "/espaces/demo/publier", data={"what": "labs"}, headers=ORIGIN
        ).text,
    )
    assert job.title == "Publier les TP"
    assert "deckz labs publish in repo--demo" in job.log


def test_jobs_refused_from_another_site(fake_deckz: Path, client: TestClient) -> None:
    response = client.post(
        "/espaces/demo/publier",
        data={"what": "labs"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert not client.app.state.studio.jobs._jobs  # ty: ignore[unresolved-attribute]


def test_jobs_outlive_studioz(tmp_path: Path) -> None:
    jobs = Jobs()
    done = jobs.submit(tmp_path, "done", [_python("print('kept')")], rerun=True)
    _wait(done)
    long = jobs.submit(
        tmp_path,
        "long",
        [_python("import time; print('started', flush=True); time.sleep(30)")],
    )
    queued = jobs.submit(tmp_path, "queued", [_python("print('never')")])
    deadline = monotonic() + 10
    while "started" not in long.log:
        assert monotonic() < deadline
        sleep(0.02)

    jobs.stop_all()  # studioz ends
    _wait(long)

    again = Jobs()
    found = {job.title: job for job in again.jobs(tmp_path)}
    assert found["done"].state is JobState.DONE
    assert found["done"].rerun
    assert list(found["done"].log) == list(done.log)
    assert found["long"].state is JobState.INTERRUPTED
    assert "started" in found["long"].log
    assert found["queued"].state is JobState.INTERRUPTED
    # The next job's number follows theirs.
    assert again.submit(tmp_path, "next", [_python("pass")]).id == queued.id + 1


def test_lanes_run_side_by_side_and_are_kept(tmp_path: Path) -> None:
    jobs = Jobs()
    sleeping = _python("import time; time.sleep(30)")
    build = jobs.submit(tmp_path, "build", [sleeping])
    link = ("Voir l'avant/après", "/espaces/demo/tp/a/demo?vue=avant-apres")
    gpu = jobs.submit(
        tmp_path, "pass", [_python("print('ran')")], lane="gpu", link=link
    )
    after = jobs.submit(tmp_path, "pass 2", [sleeping], lane="gpu")

    # The build's lane doesn't hold the GPU's back; the GPU lane's own jobs wait.
    _wait(gpu)
    assert build.state is JobState.RUNNING
    jobs.stop(tmp_path, build.id)
    jobs.stop(tmp_path, after.id)
    _wait(after)

    found = {job.title: job for job in Jobs().jobs(tmp_path)}
    assert found["pass"].lane == "gpu"
    assert found["pass"].link == link
    assert found["build"].lane == ""


def test_a_job_a_crash_left_running_is_interrupted(tmp_path: Path) -> None:
    jobs = Jobs()
    job = jobs.submit(tmp_path, "crashed", [_python("pass")])
    _wait(job)
    record = tmp_path / ".run" / "studioz" / "jobs" / f"{job.id}.json"
    kept = json.loads(record.read_text(encoding="utf8"))
    record.write_text(
        json.dumps({**kept, "state": "RUNNING", "ended": None}), encoding="utf8"
    )
    (record.parent / "broken.json").write_text("{", encoding="utf8")

    [found] = Jobs().jobs(tmp_path)

    assert found.state is JobState.INTERRUPTED
    assert found.ended is not None
    assert json.loads(record.read_text(encoding="utf8"))["state"] == "INTERRUPTED"


def test_only_the_last_jobs_are_kept(tmp_path: Path) -> None:
    jobs = Jobs()
    for i in range(32):
        _wait(jobs.submit(tmp_path, f"job {i}", [_python("pass")]))
    kept = jobs.jobs(tmp_path)
    assert len(kept) == 30
    assert kept[-1].title == "job 2"
    store = tmp_path / ".run" / "studioz" / "jobs"
    assert len(list(store.glob("*.json"))) == 30
    assert not (store / "1.log").exists()


def test_rerun_only_what_may_run_again(tmp_path: Path) -> None:
    jobs = Jobs()
    build = jobs.submit(tmp_path, "build", [_python("print('built')")], rerun=True)
    upload = jobs.submit(tmp_path, "upload", [_python("pass")], form="/dialog")
    _wait(upload)

    again = jobs.rerun(tmp_path, build.id)

    assert again is not None
    assert again.steps == build.steps
    _wait(again)
    assert "built" in again.log
    assert jobs.rerun(tmp_path, upload.id) is None


def test_build_every_deck(fake_deckz: Path, client: TestClient) -> None:
    form = client.post("/espaces/demo/construire/formulaire", headers=ORIGIN).text
    assert "Construire toutes les formations" in form
    assert 'value="fr" checked' in form
    assert 'value="en">' in form

    response = client.post(
        "/espaces/demo/construire",
        data={"kind": ["handout"], "lang": ["fr"]},
        headers=ORIGIN,
    )

    job = _job(client, response.text)
    assert job.title == "Construire toutes les formations (fr : support)"
    assert job.rerun
    assert (
        "deckz run decks --handout --no-presentation --no-print "
        "--no-part-handouts --no-html --sync --lang fr in repo--demo"
    ) in job.log
    listed = client.get("/espaces/demo/taches").text
    assert f"/taches/{job.id}/relancer" in listed

    rerun = client.post(f"/espaces/demo/taches/{job.id}/relancer", headers=ORIGIN)
    assert rerun.status_code == 200
    assert rerun.headers["HX-Trigger-After-Settle"] == "jobs-changed"
    _wait(client.app.state.studio.jobs._jobs[-1])  # ty: ignore[unresolved-attribute]


def test_an_upload_starts_again_from_its_dialog(
    fake_deckz: Path, client: TestClient
) -> None:
    job = _job(client, client.post(f"{DECK}/envoyer", headers=ORIGIN).text)
    job.state = JobState.INTERRUPTED

    listed = client.get("/espaces/demo/taches").text

    assert f'data-url="{DECK}/envoyer/formulaire">Relancer…' in listed
    assert "Interrompue par l'arrêt de studioz" in listed
    refused = client.post(f"/espaces/demo/taches/{job.id}/relancer", headers=ORIGIN)
    assert refused.status_code == 409


def test_the_status_bar_says_which_jobs_ended(
    fake_deckz: Path, client: TestClient
) -> None:
    response = client.post(
        f"{DECK}/construire",
        data={"kind": ["handout"], "lang": ["fr"]},
        headers=ORIGIN,
    )
    job = _job(client, response.text)
    job.log.extend(
        ["12:00:00 ERROR    content/a.md:3: unknown variable", "(code de sortie 1)"]
    )
    job.state = JobState.FAILED

    badge = client.get("/espaces/demo/taches/resume").text

    [ended] = json.loads(
        badge.split('data-ended="')[1].split('"')[0].replace("&#34;", '"')
    )
    assert ended["id"] == job.id
    assert ended["state"] == "failed"
    assert ended["detail"] == "content/a.md:3: unknown variable"
    assert job.ended is not None
    assert ended["ended"] == job.ended.timestamp() * 1000
