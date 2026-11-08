import json
import subprocess
from datetime import date, timedelta
from pathlib import Path
from shutil import copytree
from typing import Any

from pydantic import ValidationError
from pytest import CaptureFixture, fixture, raises

from deckz.analyzing.review import mark
from deckz.cli import main
from deckz.configuring.settings import GlobalSettings, ReviewSettings
from deckz.dashboard import Dashboard, DeckRow, _section_state, dashboard

REPORT = "reviews/sections/sec.md"
A = "content/sec/a.md"
B = "content/sec/b.md"
C = "content/sec/sub/c.md"
LAB = "labs/notebooks/sec/lab-fr.ipynb"
TWO = "company/two"
ABC = "company/abc"
INTRA = "company/INTRA/2026-01-client"
TODAY = date(2026, 11, 8)

_SETTINGS = """\
review:
  dir: reviews
  findings:
    heading: Findings
    rubrics: {E: Errors, P: Pedagogy}
    outcomes: {open: open, done: done, refused: refused}
    critical: [E]
  dated_facts:
    line: Checked on
    months: 12
  rules:
    - paths: content/sec/b.md
      since: 2026-12-01
      why: a later rule
    - paths: course-notes/sec/b.md
      since: 2026-12-01
      why: a later rule for the chapters
sessions:
  companies:
    acme: company
"""

_TITLE_PATTERN = (
    r"\s*(?P<tentative>\?\s+)?(?P<continuation>->\s+)?(?P<company>.*?)\s+-\s+"
    r"(?P<training>.*?)\s+-\s+(?P<place>.*?)(?:\s+-\s+(?P<extra>.*?))?\s*"
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")
    return path


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "--", ".")
    _git(repo, "commit", "--quiet", "-m", message)


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    # test_cli's repository, with a shared section `sec` (and its subsection
    # `sec/sub`): `company/abc` includes its `light` flavor (a.md),
    # `company/two` its `full` one (a.md, b.md, sub/c.md), and an INTRA deck
    # claiming a January session its `light` one.
    import appdirs

    root = tmp_path / "repo"
    copytree(Path(__file__).parent / "test_cli", root)
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    (root / "user-variables.yml").rename(user_dir / "variables.yml")
    _write(
        user_dir / "calendar.yml",
        json.dumps(
            {"calendar_id": "someone@example.com", "title_pattern": _TITLE_PATTERN}
        ),
    )
    monkeypatch.setattr(appdirs, "user_config_dir", lambda *_, **__: str(user_dir))
    deckz_yml = root / "deckz.yml"
    deckz_yml.write_text(deckz_yml.read_text(encoding="utf8") + _SETTINGS, "utf8")
    _write(
        root / "content" / "sec" / "sec.yml",
        "title: Sec\nflavors:\n"
        "  - name: full\n    includes: [a, b, $sub@full]\n"
        "  - name: light\n    includes: [a]\n",
    )
    _write(root / "content" / "sec" / "a.md", "# A1\n\nText.\n\n# A2\n\nMore.\n")
    _write(root / "content" / "sec" / "b.md", "# B\n")
    _write(
        root / "content" / "sec" / "sub" / "sub.yml",
        "title: Sub\nflavors:\n  - name: full\n    includes: [c]\n",
    )
    _write(root / "content" / "sec" / "sub" / "c.md", "# C1\n\n# C2\n\n# C3\n")
    _write(
        root / TWO / "deck.yml",
        "name: TWO\nparts:\n  - name: only\n    sections:\n      - $sec@full\n",
    )
    abc = root / ABC / "deck.yml"
    abc.write_text(abc.read_text(encoding="utf8") + "      - $sec@light\n", "utf8")
    _write(
        root / INTRA / "deck.yml",
        "name: CLIENT\nparts:\n  - name: only\n    sections:\n      - $sec@light\n"
        "calendar: {training: TWO, start: 2026-01-05}\n",
    )
    _write(root / LAB, "{}\n")
    _git(root, "init", "--quiet", "-b", "main")
    _commit(root, "Start")
    monkeypatch.chdir(root)
    return root


def _settings(repo: Path) -> GlobalSettings:
    return GlobalSettings.from_yaml(repo)


def _event(summary: str, start: str, days: int = 1) -> dict[str, Any]:
    first = date.fromisoformat(start)
    return {
        "id": f"{summary}-{start}",
        "htmlLink": f"https://calendar.example/{start}",
        "summary": summary,
        "status": "confirmed",
        "start": {"date": str(first)},
        "end": {"date": str(first + timedelta(days=days))},
    }


_EVENTS = [
    _event("Acme - TWO - Paris - Intra Client", "2026-01-05", 2),  # INTRA's, past
    _event("Acme - ABC - CV", "2026-12-07"),
    _event("? Acme - two - CV - with extra", "2026-11-20"),
]


def _events(tmp_path: Path) -> Path:
    return _write(tmp_path / "events.json", json.dumps(_EVENTS))


def _build(repo: Path, tmp_path: Path | None = None, **kwargs: Any) -> Dashboard:
    events = None if tmp_path is None else _events(tmp_path)
    return dashboard(_settings(repo), events_file=events, today=TODAY, **kwargs)


def _row(found: Dashboard, deck: str) -> DeckRow:
    return next(row for row in found.decks if row.deck == deck)


def _review_sec(repo: Path, **kwargs: Any) -> None:
    # The section's report records a.md, b.md and the lab, and has findings.
    mark(_settings(repo), repo / REPORT, [repo / A, repo / B, repo / LAB], **kwargs)
    report = repo / REPORT
    report.write_text(
        report.read_text(encoding="utf8")
        + "\n## Findings\n\n### Errors\n\n- **E1** — wrong. *open*\n"
        "\n### Pedagogy\n\n- **P1** — weak. *open*\n- **P2** — fixed. *done*\n",
        encoding="utf8",
    )
    _commit(repo, "Review sec")


def test_each_level_of_a_deck_is_judged_on_its_own(repo: Path) -> None:
    found = _build(repo)
    two = _row(found, TWO)
    assert two.content.ok is False
    assert two.labs.ok is None  # no report records a notebook
    assert two.dated_facts.ok is None  # nor has dated facts
    assert two.findings is not None
    assert two.findings.ok is None
    assert two.deck_pass.date is None

    _review_sec(repo, today=date(2026, 11, 1))
    two = _row(_build(repo), TWO)
    # b.md was reviewed before its rule: due, read whole again.
    assert two.content.counts == {"fresh": 1, "due": 1, "unreviewed": 1}
    assert two.content.to_review == 2
    assert two.frames == 4  # c.md's 3, unreviewed, and b.md's
    assert two.labs.ok is True
    assert two.findings is not None
    assert (two.findings.open, two.findings.critical, two.findings.ok) == (
        {"E": 1, "P": 1},
        1,
        False,
    )
    assert two.dated_facts.ok is True

    _write(repo / LAB, '{"cells": []}\n')
    mark(_settings(repo), repo / "reviews" / f"{TWO}.md", [], today=TODAY)
    late = _row(_build(repo), TWO)
    assert late.labs.ok is False
    assert late.deck_pass.holds
    facts = _row(dashboard(_settings(repo), today=date(2028, 1, 1)), TWO).dated_facts
    assert facts.ok is False
    assert facts.due == (REPORT,)


def test_decks_come_by_next_session_then_frames(repo: Path, tmp_path: Path) -> None:
    found = _build(repo, tmp_path)
    assert found.sessions.available
    # The decks with a session first, by its start; test_cli's others after.
    assert [row.deck for row in found.decks][:2] == [TWO, ABC]
    assert INTRA not in [row.deck for row in found.decks]
    two = found.decks[0]
    assert two.next_session is not None
    assert (two.next_session.start, two.next_session.tentative) == (
        date(2026, 11, 20),
        True,
    )
    assert found.left_out == (INTRA,)

    every = _build(repo, tmp_path, include_past=True)
    intra = _row(every, INTRA)
    assert (intra.intra, intra.past, intra.next_session) == (True, True, None)
    assert every.left_out == ()

    # With no session, by frames to review, then path.
    _review_sec(repo)
    rows = _build(repo, include_past=True).decks
    assert [(-r.frames, r.deck) for r in rows] == sorted(
        (-r.frames, r.deck) for r in rows
    )


def test_without_the_calendar_a_past_intra_is_judged_by_its_start(
    repo: Path, tmp_path: Path
) -> None:
    (tmp_path / "user" / "calendar.yml").unlink()
    found = _build(repo)
    assert not found.sessions.available
    assert found.sessions.why
    assert all(row.sessions is None for row in found.decks)
    assert found.left_out == (INTRA,)  # its start is over 31 days old

    found = dashboard(_settings(repo), today=date(2026, 1, 20))
    assert found.left_out == ()


def test_the_totals(repo: Path) -> None:
    _review_sec(repo, today=date(2026, 11, 1))
    found = _build(repo)
    totals = found.totals
    sections = {row.section: row.state for row in found.sections}
    assert sections["sec"] == "due"  # b.md, reviewed before its rule
    assert sections["sec/sub"] == "none"
    assert totals.sections["due"] == 1
    assert totals.files["unreviewed"] >= 1
    assert totals.findings is not None
    assert totals.findings.open == {"E": 1, "P": 1}
    assert (totals.findings.critical, totals.findings.done) == (1, 1)
    assert totals.findings.reports_with_open == 1
    assert [(r.rule.paths, r.due) for r in totals.rules] == [("content/sec/b.md", 1)]
    sec = next(row for row in found.sections if row.section == "sec")
    assert set(sec.decks) == {ABC, TWO, INTRA}
    assert sec.needs_care


def test_a_sections_state() -> None:
    from deckz.analyzing.review import FileReview

    def state(*states: Any) -> str:
        return _section_state([FileReview(f"f{i}", s) for i, s in enumerate(states)])

    assert state("unreviewed", "unreviewed") == "none"
    assert state("fresh", "stale", "unreviewed") == "stale"
    assert state("fresh", "deleted") == "stale"
    assert state("fresh", "unreviewed") == "partial"
    assert state("fresh", "due") == "due"
    assert state("fresh") == "fresh"


def test_critical_rubrics_must_be_rubrics() -> None:
    with raises(ValidationError, match="lacks: X"):
        ReviewSettings.model_validate(
            {
                "dir": "reviews",
                "findings": {
                    "heading": "Findings",
                    "rubrics": {"E": "Errors"},
                    "outcomes": {"open": "o", "done": "d", "refused": "r"},
                    "critical": ["X"],
                },
            }
        )


def test_cli_json_names_no_client(
    repo: Path, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    _review_sec(repo)
    main(("dashboard", "--json", "--events", str(_events(tmp_path))))
    found = json.loads(capsys.readouterr().out)
    assert list(found) == [
        "today",
        "sessions",
        "totals",
        "decks",
        "left_out",
        "sections",
        "problems",
    ]
    deck = found["decks"][0]
    assert list(deck["levels"]) == [
        "content",
        "labs",
        "pass",
        "dated_facts",
        "findings",
    ]
    assert deck["opens"] is None  # no chapter due, no deck report
    section = found["sections"][0]
    assert section["needs_care"] is True
    assert set(section["opens"]) == {"file", "why"}
    assert deck["next_session"] == {
        "start": "2026-11-20",
        "end": "2026-11-20",
        "days": 1,
        "tentative": True,
        "intra": False,
        "calendar": None,
    }
    text = json.dumps(found)
    assert "Paris" not in text
    assert "with extra" not in text
    assert "Client" not in text


def test_cli_human_output(
    repo: Path, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    _review_sec(repo)
    main(("dashboard", "--events", str(_events(tmp_path))))
    out, err = capsys.readouterr()
    lines = out.splitlines()
    assert lines[0].startswith("Sections  ")
    assert any(
        line.startswith("Findings  2 open in 1 reports (E 1, P 1)") for line in lines
    )
    header = next(line for line in lines if " deck " in f" {line} ")
    assert header.startswith("next ")
    assert "1 past INTRA decks left out (--all shows them)" in err
    assert "calendar from the events file" in err


def test_a_decks_course_notes_reports_cover_it(
    repo: Path, capsys: CaptureFixture[str]
) -> None:
    chapter = "course-notes/sec/a.md"
    notes_report = "reviews/course-notes/sec.md"
    _write(repo / chapter, "# A\n\nWritten out.\n")
    _commit(repo, "Chapter")
    mark(_settings(repo), repo / notes_report, [repo / chapter])
    report = repo / notes_report
    report.write_text(
        report.read_text(encoding="utf8")
        + "\n## Findings\n\n### Errors\n\n- **E1** — cut. *open*\n",
        encoding="utf8",
    )

    two = _row(_build(repo), TWO)
    assert two.findings is not None
    assert two.findings.reports == (notes_report,)
    assert two.findings.critical == 1

    main(("review", "findings", TWO, "--plain"))
    assert capsys.readouterr().out.startswith(f"{notes_report}\t")


def _opens(row: Any) -> tuple[str, str] | None:
    return None if row.opens is None else (row.opens.file, row.opens.why)


def _section(found: Dashboard, section: str) -> Any:
    return next(row for row in found.sections if row.section == section)


def test_a_section_opens_a_chapter_else_a_report_else_a_file(repo: Path) -> None:
    found = _build(repo)
    # Nothing reviewed, no chapter: its first file to review.
    assert _opens(_section(found, "sec")) == (A, "file")
    assert _opens(_section(found, "sec/sub")) == (C, "file")

    _write(repo / "course-notes/sec/a.md", "# A\n")
    _commit(repo, "Chapter")
    assert _opens(_section(_build(repo), "sec")) == ("course-notes/sec/a.md", "chapter")

    # c.md, never reviewed, has no chapter: the report of its section.
    mark(_settings(repo), repo / "reviews/sections/sub.md", [repo / C], today=TODAY)
    _write(repo / C, "# C1\n\nChanged.\n")
    _commit(repo, "Change c")
    assert _opens(_section(_build(repo), "sec/sub")) == (
        "reviews/sections/sub.md",
        "report",
    )

    # Fresh, after its rule: its open findings, in its report.
    _review_sec(repo, today=date(2026, 12, 2))
    sec = _section(_build(repo), "sec")
    assert (sec.state, sec.needs_care) == ("fresh", True)
    assert _opens(sec) == (REPORT, "report")


def test_a_chapter_due_comes_first(repo: Path) -> None:
    chapter = "course-notes/sec/b.md"
    _review_sec(repo, today=date(2026, 11, 1))
    _write(repo / chapter, "# B\n")
    _commit(repo, "Chapter")
    mark(
        _settings(repo),
        repo / "reviews/course-notes/sec.md",
        [repo / chapter],
        today=date(2026, 11, 1),
    )
    found = _build(repo)
    assert _opens(_section(found, "sec")) == (chapter, "chapter_due")
    assert _opens(_row(found, TWO)) == (chapter, "chapter_due")
    # abc has no chapter due and no deck report: its deck page.
    assert _row(found, ABC).opens is None

    mark(_settings(repo), repo / "reviews" / f"{ABC}.md", [], today=TODAY)
    abc = _row(_build(repo), ABC)
    assert _opens(abc) == (abc.deck_pass.report, "report")
