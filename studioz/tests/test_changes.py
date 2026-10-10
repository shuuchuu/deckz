import shutil
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from fastapi.testclient import TestClient
from pytest import fixture, mark
from studioz.app import create_app
from studioz.baselines import BASELINES_DIR, Baselines, scratch_path
from studioz.changes import Affected, ChangedFile, LangPairs, grouped
from studioz.comparison import Row, _signature, compare, signatures
from studioz.watches import Watches
from studioz_pdfs import write_pdf

from deckz.analyzing.frames import Frame

ORIGIN = {"Origin": "http://localhost:8421"}
DECK = "/espaces/demo/formations/client/abc"
poppler = mark.skipif(shutil.which("pdftoppm") is None, reason="needs poppler")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(cwd),
            "-c",
            "user.name=test",
            "-c",
            "user.email=t@e.com",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _write(workspace: Path, path: str, text: str = "x\n") -> Path:
    file = workspace / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf8")
    return file


def _commit(workspace: Path, message: str = "Content") -> None:
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-m", message)


def test_changes_grouped_with_lone_translations(workspace: Path) -> None:
    for path in (
        "content/a/x.md",
        "content/a/en/x.md",
        "content/a/y.md",
        "content/a/en/y.md",
        "client/abc/content/about.md",
        "client/abc/content/en/about.md",
        "README.md",
    ):
        _write(workspace, path)
    _commit(workspace)
    _write(workspace, "content/a/x.md", "changed\n")
    _write(workspace, "content/a/y.md", "changed\n")
    _write(workspace, "content/a/en/y.md", "changed\n")
    _write(workspace, "client/abc/content/en/about.md", "changed\n")
    _write(workspace, "content/a/z.md")
    _write(workspace, "labs/notebooks/t/demo-en.ipynb")
    _write(workspace, "labs/notebooks/t/demo-fr.ipynb")
    _write(workspace, "assets/img/new.png")
    (workspace / "README.md").unlink()

    pairs = LangPairs().get(workspace)
    groups = {group.title: group for group in grouped(workspace, ["client/abc"], pairs)}

    assert list(groups) == [
        "client/abc",
        "Contenu partagé",
        "Labs",
        "Images et thème",
        "Autres fichiers",
    ]
    assert groups["client/abc"].deck == "client/abc"
    assert groups["client/abc"].files == (
        ChangedFile(
            "client/abc/content/en/about.md",
            "modifié",
            "client/abc/content/about.md",
            editable=True,
        ),
    )
    shared = {file.path: file.other_lang for file in groups["Contenu partagé"].files}
    assert shared == {
        "content/a/x.md": "content/a/en/x.md",
        "content/a/y.md": None,
        "content/a/en/y.md": None,
        # deckz's rule: a new French file needs its English one too.
        "content/a/z.md": "content/a/en/z.md",
    }
    assert {file.other_lang for file in groups["Labs"].files} == {None}
    assert groups["Images et thème"].files[0].status == "nouveau"
    assert groups["Autres fichiers"].files == (
        ChangedFile("README.md", "supprimé", None, editable=False),
    )


def test_changes_panel(workspace: Path, repository: Path) -> None:
    _write(workspace, "content/a/x.md")
    affected = Affected(lambda _: [sys.executable, "-c", "print('[\"client/abc\"]')"])
    client = TestClient(
        create_app(repository, affected=affected), base_url="http://localhost:8421"
    )
    url = "/espaces/demo/modifications?formation=client/abc&lang=fr"

    deadline = monotonic() + 10
    while "Recherche des formations" in (page := client.get(url).text):
        assert monotonic() < deadline, "timed out"
        sleep(0.05)

    assert 'data-file="content/a/x.md"' in page
    assert f'href="{DECK}?lang=fr&vue=modifications"' in page


def _frame(page: int, title: str) -> Frame:
    return Frame(page, title, f"content/{title}.md", 1)


def test_compare_matches_frames_by_title() -> None:
    before = {2: "A", 3: "B", 4: "C", 5: "D", 6: "E"}
    before_looks = ("title", "a", "b", "c", "d", "e")
    # X inserted (renumbering what follows), B changed, C removed, D the
    # same, E retitled.
    after = [_frame(2, "A"), _frame(3, "X"), _frame(4, "B"), _frame(5, "D")]
    after += [_frame(6, "E2")]
    after_looks = ("title", "a", "x", "b2", "d", "e2")

    result = compare(before, before_looks, after, after_looks)

    assert result.unchanged == 2
    assert result.rows == (
        Row("new", "X", None, 3, "content/X.md", 1),
        Row("changed", "B", 3, 4, "content/B.md", 1),
        Row("removed", "C", 4, None),
        Row("changed", "E2", 6, 6, "content/E2.md", 1, "E"),
    )
    assert (result.count("changed"), result.count("new")) == (2, 1)


def _pgm(width: int, height: int, dark: tuple[int, int] | None) -> bytes:
    pixels = bytearray(b"\xff" * (width * height))
    if dark:
        pixels[dark[1] * width + dark[0]] = 0
    return f"P5\n{width} {height}\n255\n".encode() + bytes(pixels)


def test_signatures_ignore_the_frame_number() -> None:
    blank = _signature(_pgm(100, 50, None))

    assert _signature(_pgm(100, 50, (95, 48))) == blank
    assert _signature(_pgm(100, 50, (50, 48))) != blank
    assert _signature(_pgm(100, 50, (95, 10))) != blank


@poppler
def test_signatures_of_a_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    write_pdf(pdf, [(10, 150), (390, 0), (10, 150), (200, 150)])

    found = signatures(pdf)

    assert len(found) == 4
    # The second page's square is in the frame number's corner.
    assert found[0] == found[2] != found[3]
    assert len(set(found)) == 3


# Stands for `deckz run` of the handout, in the deck's directory: a PDF whose
# frames are the `# ` headings of `content/slides.md`, one square per frame
# placed by the frame's text, and the record of its frame markers.
_FAKE_BUILD = """
import json, pathlib, sys

sys.path.insert(0, sys.argv[1])
from studioz_pdfs import write_pdf

deck = pathlib.Path.cwd()
build = deck / ".build" / "abc-handout"
build.mkdir(parents=True, exist_ok=True)
text = (deck / "content" / "slides.md").read_text()
fragment = build / "content" / "slides-0123456789abcdef.md"
fragment.parent.mkdir(exist_ok=True)
fragment.write_text(text)
frames = [part.splitlines() for part in text.split("# ")[1:]]
(build / "abc-handout.typ").write_text("")
(deck / "pdf").mkdir(exist_ok=True)
pdf = deck / "pdf" / "abc-handout.pdf"
boxes = [(10, 10)] + [(10 + 10 * len(lines[-1]), 150) for lines in frames]
write_pdf(pdf, boxes)
(build / "abc-handout.pdf").write_bytes(pdf.read_bytes())
markers = [
    {"fragment": str(fragment), "index": index, "page": index + 2}
    for index in range(len(frames))
]
(build / "abc-handout.markers.json").write_text(json.dumps({"deckz-frame": markers}))
"""


@fixture
def fake_build(tmp_path: Path, workspace: Path) -> list[str]:
    # As in a real repository, builds are ignored.
    with (workspace / ".gitignore").open("a", encoding="utf8") as gitignore:
        gitignore.write(".build/\npdf/\n")
    _commit(workspace, "Ignore builds")
    script = tmp_path / "fake_build.py"
    script.write_text(_FAKE_BUILD, encoding="utf8")
    return [sys.executable, str(script), str(Path(__file__).parent)]


def _slides(workspace: Path, frames: dict[str, str]) -> None:
    text = "".join(f"# {title}\n\n{body}\n" for title, body in frames.items())
    _write(workspace, "client/abc/content/slides.md", text)


def _build(workspace: Path, command: list[str]) -> None:
    subprocess.run(command, cwd=workspace / "client" / "abc", check=True)


def _baseline(baselines: Baselines, workspace: Path) -> Any:
    deadline = monotonic() + 30
    while (state := baselines.get(workspace, workspace / "client/abc", "fr")).building:
        assert monotonic() < deadline, "timed out"
        sleep(0.05)
    return state


def test_baseline_captured_from_a_build_of_the_commit(
    workspace: Path, fake_build: list[str]
) -> None:
    _slides(workspace, {"One": "a", "Two": "b"})
    _commit(workspace)
    _build(workspace, fake_build)
    baselines = Baselines(lambda *_: fake_build)
    deck = workspace / "client" / "abc"

    assert baselines.capture(workspace, deck, "fr")
    assert not baselines.capture(workspace, deck, "fr")  # Already there.

    state = baselines.get(workspace, deck, "fr")
    assert state.baseline is not None
    assert state.baseline.titles == {2: "One", 3: "Two"}
    assert not scratch_path(workspace).exists()

    # A build with changes isn't the commit's.
    _slides(workspace, {"One": "changed"})
    _git(workspace, "commit", "-am", "Changed")
    _write(workspace, "client/abc/content/slides.md", "# Uncommitted\n")
    _build(workspace, fake_build)
    assert not baselines.capture(workspace, deck, "fr")


@poppler
def test_baseline_built_in_a_scratch_checkout(
    workspace: Path, repository: Path, fake_build: list[str]
) -> None:
    _slides(workspace, {"One": "a", "Two": "b", "Three": "c"})
    _commit(workspace)
    commit = _git(workspace, "rev-parse", "HEAD").strip()
    _slides(workspace, {"One": "a", "New": "n", "Two": "bb"})
    _build(workspace, fake_build)
    baselines = Baselines(lambda *_: fake_build)

    state = _baseline(baselines, workspace)

    assert state.error is None
    assert state.baseline.titles == {2: "One", 3: "Two", 4: "Three"}
    assert state.baseline.pdf.parent == (
        workspace / BASELINES_DIR / commit / "client" / "abc" / "fr"
    )
    # The baseline is there just before its scratch checkout is removed.
    deadline = monotonic() + 10
    while scratch_path(workspace).exists():
        assert monotonic() < deadline, "scratch checkout never removed"
        sleep(0.05)
    worktrees = _git(workspace, "worktree", "list")
    assert ".baseline" not in worktrees

    # The before/after view, with the deck's live build.
    watches = Watches(command=lambda *_: [sys.executable, "-c", "pass"])
    client = TestClient(
        create_app(repository, watches=watches, baselines=baselines),
        base_url="http://localhost:8421",
    )
    watch = watches.watch(workspace, workspace / "client" / "abc", "fr")
    watch._parse("12:00:00 INFO     Initial build finished")
    page = client.get(f"{DECK}/comparaison?lang=fr").text

    assert "1 cadre modifié" in page
    assert "1 nouveau" in page
    assert "1 supprimé" in page
    assert "1 inchangé" in page
    assert 'data-file="client/abc/content/slides.md" data-line="4"' in page
    assert client.get(f"{DECK}/avant.pdf?lang=fr").content.startswith(b"%PDF")


def test_live_build_kept_as_the_baseline_at_commit(
    workspace: Path, repository: Path, fake_build: list[str]
) -> None:
    _slides(workspace, {"One": "a"})
    _commit(workspace)
    _slides(workspace, {"One": "a", "Two": "b"})
    _build(workspace, fake_build)
    # A scratch build would fail: the baseline must be the live one.
    baselines = Baselines(lambda *_: [sys.executable, "-c", "exit(1)"])
    # The deck's page keeps its watch running.
    sleeping = [sys.executable, "-c", "import time; time.sleep(60)"]
    watches = Watches(command=lambda *_: sleeping)
    client = TestClient(
        create_app(repository, watches=watches, baselines=baselines),
        base_url="http://localhost:8421",
    )
    deck = workspace / "client" / "abc"
    before = _git(workspace, "rev-parse", "HEAD")
    watch = watches.watch(workspace, deck, "fr")
    try:
        watch._parse("12:00:00 INFO     Initial build finished")
        client.post(
            "/espaces/demo/commit",
            data={
                "path": "client/abc/content/slides.md",
                "message": "Two",
                "lang_sync": "pending",
                "formation": "client/abc",
                "lang": "fr",
            },
            headers=ORIGIN,
        )
    finally:
        watches.stop_all()

    assert _git(workspace, "rev-parse", "HEAD") != before
    state = baselines.get(workspace, deck, "fr")
    assert state.baseline is not None
    assert state.baseline.titles == {2: "One", 3: "Two"}


def test_failed_baseline_build_and_retry(
    workspace: Path, repository: Path, fake_build: list[str]
) -> None:
    _slides(workspace, {"One": "a"})
    _commit(workspace)
    _slides(workspace, {"One": "b"})
    failing = [sys.executable, "-c", "print('12:00:00 ERROR    Boom'); exit(1)"]
    baselines = Baselines(lambda *_: failing)

    state = _baseline(baselines, workspace)

    assert state.error == "12:00:00 ERROR    Boom"
    client = TestClient(
        create_app(repository, baselines=baselines), base_url="http://localhost:8421"
    )
    assert "Réessayer" in client.get(f"{DECK}/comparaison?lang=fr").text
    baselines._command = lambda *_: fake_build
    client.post(f"{DECK}/comparaison/reessayer?lang=fr", headers=ORIGIN)
    assert _baseline(baselines, workspace).baseline is not None


def test_a_new_deck_has_an_empty_baseline(workspace: Path) -> None:
    _write(workspace, "client/new/deck.yml", "name: new\n")
    baselines = Baselines(lambda *_: [sys.executable, "-c", "exit(1)"])

    deadline = monotonic() + 10
    while (state := baselines.get(workspace, workspace / "client/new", "fr")).building:
        assert monotonic() < deadline, "timed out"
        sleep(0.05)

    assert state.baseline is not None
    assert state.baseline.pdf is None
    assert state.baseline.titles == {}


def test_nothing_to_compare_without_changes(
    client: TestClient, workspace: Path
) -> None:
    page = client.get(f"{DECK}/comparaison?lang=fr").text

    assert "Rien n'a changé" in page
    deck = client.get(f"{DECK}?vue=modifications").text
    assert 'data-view="changes"' in deck
    assert "comparison-refresh from:body, load" in deck
