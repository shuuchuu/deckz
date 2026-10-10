import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep

from fastapi.testclient import TestClient
from studioz.app import create_app
from studioz.problems import Statuses, StatusReport, build_problems, locate
from studioz.watches import Snapshot, State

# Stands for `deckz status --json`: counts its runs, and reports a check
# problem naming a content file.
_FAKE_STATUS = """
import json, pathlib, sys

runs = pathlib.Path(sys.argv[1])
before = runs.read_text() if runs.exists() else ""
runs.write_text(before + sys.argv[2] + "\\n")
print(json.dumps({"scope": "", "sections": [
    {"key": "checks", "title": "Checks", "summary": "1 problem", "items": [
        {"text": "lab-frames: content/greeting/hello.md:2: no lab link", "fix": ""}]},
    {"key": "translation", "title": "Translation", "summary": "", "items": []},
    {"key": "decks", "title": "Built decks", "summary": "", "items": [
        {"text": "client/abc: 1 PDF not matching its content", "fix": "deckz run"}]},
]}))
"""


def _content(workspace: Path) -> Path:
    path = workspace / "content" / "greeting" / "hello.md"
    path.parent.mkdir(parents=True)
    path.write_text("Intro\n# Hello\n\nText\n", encoding="utf8")
    return path


def _fake(tmp_path: Path) -> tuple[Statuses, Path]:
    script = tmp_path / "fake_status.py"
    script.write_text(_FAKE_STATUS, encoding="utf8")
    runs = tmp_path / "runs.txt"
    return Statuses(
        "main", lambda _, since: [sys.executable, str(script), str(runs), str(since)]
    ), runs


def _finished(statuses: Statuses, workspace: Path) -> StatusReport:
    deadline = monotonic() + 10
    while (report := statuses.report(workspace)).running:
        assert monotonic() < deadline, "timed out"
        sleep(0.05)
    return report


def test_locate_names_editable_files_only(workspace: Path) -> None:
    _content(workspace)
    hello = workspace / "content" / "greeting" / "hello.md"

    assert locate(workspace, f"{hello}:4: unexpected end") == (
        "content/greeting/hello.md",
        4,
    )
    assert locate(workspace, "lab-frames: content/greeting/hello.md: x") == (
        "content/greeting/hello.md",
        None,
    )
    assert locate(workspace, "labs/x.ipynb: no ID") == (None, None)
    assert locate(workspace, "/elsewhere/content/greeting/hello.md:1: x") == (
        None,
        None,
    )


def test_status_runs_again_only_after_a_change(tmp_path: Path, workspace: Path) -> None:
    hello = _content(workspace)
    statuses, runs = _fake(tmp_path)

    report = _finished(statuses, workspace)

    assert report.result is not None
    (group,) = report.result  # The built decks aren't a problem here.
    assert group.title == "Vérifications"
    (problem,) = group.problems
    assert (problem.file, problem.line) == ("content/greeting/hello.md", 2)
    # Changes count from the merge base with the branch synced with.
    base = subprocess.run(
        ["git", "-C", str(workspace), "merge-base", "HEAD", "main"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert runs.read_text().split() == base

    _finished(statuses, workspace)
    assert len(runs.read_text().split()) == 1

    hello.write_text("# Changed\n", encoding="utf8")
    _finished(statuses, workspace)
    assert len(runs.read_text().split()) == 2


def test_a_failed_status_says_why(workspace: Path) -> None:
    statuses = Statuses(
        None, lambda *_: [sys.executable, "-c", "raise SystemExit('boom')"]
    )

    report = _finished(statuses, workspace)

    assert report.error == "boom"
    assert report.result is None


def test_build_problems_link_the_failing_file(workspace: Path) -> None:
    hello = _content(workspace)
    failed = Snapshot(State.FAILED, (f"{hello}:2: unexpected '}}'",), 0, 0)

    group = build_problems(workspace, failed)

    assert group is not None
    assert (group.problems[0].file, group.problems[0].line) == (
        "content/greeting/hello.md",
        2,
    )
    # Shown relative to the workspace.
    assert group.problems[0].text == "content/greeting/hello.md:2: unexpected '}'"
    assert build_problems(workspace, Snapshot(State.BUILT, (), 1, 1)) is None


def _panel(repository: Path, statuses: Statuses) -> Callable[[str], str]:
    client = TestClient(
        create_app(repository, statuses=statuses), base_url="http://localhost:8421"
    )

    def get(query: str) -> str:
        deadline = monotonic() + 10
        while "every 2s" in (
            text := client.get(f"/espaces/demo/problemes{query}").text
        ):
            assert monotonic() < deadline, "timed out"
            sleep(0.05)
        return text

    return get


def test_panel_with_the_deck_s_shrunk_frames(
    tmp_path: Path, repository: Path, workspace: Path
) -> None:
    _content(workspace)
    panel = _panel(repository, _fake(tmp_path)[0])

    page = panel("")
    assert "Vérifications" in page
    # Without a deck, nothing to open the file in.
    assert 'class="problem"' in page
    assert "data-file" not in page

    deck = workspace / "client" / "abc"
    build = deck / ".build" / "abc-handout"
    fragment = build / "greeting" / "hello-0123456789abcdef.md"
    fragment.parent.mkdir(parents=True)
    fragment.write_text("Intro\n# Hello\n\nText\n", encoding="utf8")
    (build / "abc-handout.typ").write_text("", encoding="utf8")
    (build / "abc-handout.pdf").write_bytes(b"%PDF-1.4")
    (deck / "pdf").mkdir()
    (deck / "pdf" / "abc-handout.pdf").write_bytes(b"%PDF-1.4")
    markers = {
        "deckz-frame": [{"fragment": str(fragment), "index": 0, "page": 3}],
        "formation-overflow": [{"ratio": "93.7%", "page": 3}],
    }
    (build / "abc-handout.markers.json").write_text(json.dumps(markers), "utf8")

    page = panel("?formation=client/abc&lang=fr")

    assert "Cadres réduits" in page
    assert "p. 3 « Hello » réduit à 93,7 %" in page
    assert 'data-file="content/greeting/hello.md"' in page
    assert 'data-line="2"' in page
    assert 'data-page="3"' in page
    assert "workspace-changed from:body" in page
