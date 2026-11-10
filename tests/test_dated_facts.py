import subprocess
from collections import Counter
from dataclasses import replace
from datetime import date
from json import loads
from pathlib import Path
from typing import Any

from pytest import fixture, raises

from deckz.analyzing.content_checks import CHECKS, OPT_IN
from deckz.analyzing.dated_facts import (
    DatedFacts,
    add_months,
    dated_facts,
    dated_facts_problems,
    list_problems,
    schedule,
)
from deckz.analyzing.findings import compact, fiche, parse
from deckz.cli import main
from deckz.configuring.settings import GlobalSettings

TODAY = date(2026, 11, 10)

DATED = (
    "review:\n  dir: reviews\n  dated_facts:\n    line: Checked on\n"
    "    months: 12\n    sections: {fast: 6, fast/slow: 9}\n"
)


def _git(repo: Path, *args: str, **env: str) -> None:
    import os

    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, **env},
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    root = tmp_path / "repo"
    _write(root / "deckz.yml", DATED)
    _write(root / "reviews" / "sections" / "fast" / "tool.md", "# Tool\n")
    _write(
        root / "reviews" / "sections" / "fast" / "slow" / "deep.md",
        "# Deep\n\nChecked on 2026-01-15, against the docs.\nChecked on 2025-01-01\n",
    )
    _write(root / "reviews" / "sections" / "old" / "x.md", "# X\n")
    _write(root / "reviews" / "decks" / "d.md", "# Not a section report\n")
    _git(root, "init", "--quiet", "-b", "main")
    _git(root, "add", ".")
    day = "2026-01-10T12:00:00+00:00"
    _git(
        root,
        "commit",
        "--quiet",
        "-m",
        "Start",
        GIT_AUTHOR_DATE=day,
        GIT_COMMITTER_DATE=day,
        GIT_AUTHOR_NAME="a",
        GIT_AUTHOR_EMAIL="a@b",
        GIT_COMMITTER_NAME="a",
        GIT_COMMITTER_EMAIL="a@b",
    )
    # A rename keeps the day it was added.
    (root / "reviews" / "sections" / "new").mkdir()
    _git(root, "mv", "reviews/sections/old/x.md", "reviews/sections/new/x.md")
    _git(
        root,
        "commit",
        "--quiet",
        "-m",
        "Move",
        GIT_AUTHOR_NAME="a",
        GIT_AUTHOR_EMAIL="a@b",
        GIT_COMMITTER_NAME="a",
        GIT_COMMITTER_EMAIL="a@b",
    )
    monkeypatch.chdir(root)
    return root


def test_dated_facts_read_the_line_or_the_day_added(repo: Path) -> None:
    found = {f.section: f for f in dated_facts(GlobalSettings.from_yaml(repo))}

    assert set(found) == {"fast/tool", "fast/slow/deep", "new/x"}
    assert (found["fast/tool"].checked, found["fast/tool"].source) == (
        date(2026, 1, 10),
        "added",
    )
    assert found["fast/tool"].months == 6
    assert (found["fast/slow/deep"].checked, found["fast/slow/deep"].months) == (
        date(2026, 1, 15),
        9,
    )
    assert found["fast/slow/deep"].source == "line"
    assert (found["new/x"].checked, found["new/x"].months) == (date(2026, 1, 10), 12)


def test_the_check_names_the_reports_due(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)

    # Alone of its delay, a report is due in its deadline's month, from its
    # first day.
    assert dated_facts_problems(settings, None, today=date(2026, 6, 30)) == []
    problems = dated_facts_problems(settings, None, today=date(2026, 7, 1))
    assert len(problems) == 1
    assert problems[0].startswith(
        "reviews/sections/fast/tool.md: dated facts due since 2026-07, never"
    )
    assert "at the latest by 2026-07-10" in problems[0]
    assert "`Checked on YYYY-MM-DD` line" in problems[0]
    later = dated_facts_problems(settings, None, today=date(2027, 1, 11))
    assert [p.split(":")[0] for p in later] == [
        "reviews/sections/fast/slow/deep.md",
        "reviews/sections/fast/tool.md",
        "reviews/sections/new/x.md",
    ]
    only = dated_facts_problems(
        settings, [repo / "reviews/sections/new/x.md"], today=date(2027, 1, 11)
    )
    assert len(only) == 1
    assert "review-dated-facts" in OPT_IN


def test_add_months_clamps_to_the_months_end() -> None:
    assert add_months(date(2026, 8, 31), 6) == date(2027, 2, 28)
    assert add_months(date(2026, 1, 15), 12) == date(2027, 1, 15)


########################################################################################
# The spreading                                                                        #
########################################################################################


def _facts(section: str, checked: date, months: int = 6) -> DatedFacts:
    return DatedFacts(f"r/{section}.md", section, checked, "line", months)


def test_the_schedule_spreads_reports_written_together() -> None:
    # Twelve reports checked the same week, every 6 months: two a month.
    found = [_facts(f"s{i:02}", date(2026, 10, 20 + i % 5)) for i in range(12)]

    due = schedule(found)

    months = Counter(f"{day:%Y-%m}" for day in due.values())
    assert months == {
        f"{m}": 2
        for m in ("2026-11", "2026-12", "2027-01", "2027-02", "2027-03", "2027-04")
    }
    for facts in found:
        day = due[facts.report]
        assert day.day == 1
        assert facts.deadline is not None
        # Never after the deadline, always after the month it was checked in.
        assert day <= facts.deadline
        assert (day.year, day.month) > (facts.checked.year, facts.checked.month)  # type: ignore[union-attr]
    # Ties go by path: the first ones keep the latest months.
    assert due["r/s00.md"] == due["r/s01.md"] == date(2027, 4, 1)


def test_the_schedule_brings_forward_only_what_the_cap_needs() -> None:
    # Spread already: each keeps its deadline's month.
    found = [_facts(f"s{i}", date(2026, 1 + i, 3)) for i in range(6)]
    due = schedule(found)
    assert [due[f.report] for f in found] == [date(2026, 7 + i, 1) for i in range(6)]

    # Checked in its month, a report's next deadline is its due month: the
    # spreading holds with no more advance.
    rechecked = [replace(found[0], checked=date(2026, 7, 15)), *found[1:]]
    assert schedule(rechecked)["r/s0.md"] == date(2027, 1, 1)
    assert {r: d for r, d in schedule(rechecked).items() if r != "r/s0.md"} == {
        r: d for r, d in due.items() if r != "r/s0.md"
    }


def test_each_delay_is_spread_on_its_own() -> None:
    six = [_facts(f"a{i}", date(2026, 10, 1)) for i in range(6)]
    twelve = [_facts(f"b{i}", date(2026, 10, 1), 12) for i in range(12)]

    due = schedule([*six, *twelve])

    assert Counter(f"{due[f.report]:%Y-%m}" for f in six) == {
        f"{y}-{m:02}": 1
        for y, m in [(2026, 11), (2026, 12)] + [(2027, i) for i in range(1, 5)]
    }
    assert len({due[f.report] for f in twelve}) == 12
    assert max(due[f.report] for f in twelve) == date(2027, 10, 1)


def test_a_report_with_no_date_has_no_due_month() -> None:
    facts = DatedFacts("r/x.md", "x", None, None, 6)

    assert schedule([facts]) == {}
    assert facts.deadline is None
    assert not facts.due(date(2030, 1, 1))


########################################################################################
# The list                                                                             #
########################################################################################


LISTED = (
    "review:\n  dir: reviews\n"
    "  findings:\n    heading: Findings\n    rubrics: {E: Errors}\n"
    "    outcomes: {open: open, done: done, refused: refused}\n"
    "  dated_facts:\n    line: Checked on\n    heading: Dated facts\n"
)

HEADER = "| File | Frame | Fact | As of | Source |\n| --- | --- | --- | --- | --- |\n"

REPORT_BODY = (
    "# Sec\n\n## Fiche\n\nChecked on 2026-10-01.\n\n"
    "## Findings\n\n### Errors\n\n- **E1** — `a.md`: wrong. *done* (abc1234)\n\n"
    "## Dated facts\n\nChecked against the vendors' pages.\n\n" + HEADER
)


@fixture
def listed(tmp_path: Path, monkeypatch: Any) -> Path:
    root = tmp_path / "listed"
    _write(root / "deckz.yml", LISTED)
    _write(root / "content" / "sec" / "a.md", "# A\n")
    _write(root / "labs" / "notebooks" / "sec" / "lab" / "demo-fr.ipynb", "{}\n")
    _write(root / "reviews" / "decks" / "d.md", "# D\n")
    _git(root, "init", "--quiet", "-b", "main")
    monkeypatch.chdir(root)
    return root


ROWS = (
    "| `a.md` | Models | The largest context window is one million tokens. "
    "| 2026-06 | the model's knowledge |\n"
    "| lab/demo-fr.ipynb | [3] | The `pipe \\| tee` call is in pandas 3.0. "
    "| 2026-10-14 | https://pandas.pydata.org |\n"
    "| content/sec/a.md | Prices | Prompt caching bills a reread at 10 % of the input. "
    "| 2026-11-01 | the vendor's pricing page |\n"
)


def test_a_list_is_read_row_by_row(listed: Path) -> None:
    _write(listed / "reviews" / "sections" / "sec.md", REPORT_BODY + ROWS)
    settings = GlobalSettings.from_yaml(listed)

    (facts,) = dated_facts(settings, today=TODAY)

    assert facts.listed
    assert [(f.line, f.file, f.frame, f.date) for f in facts.facts] == [
        (19, "a.md", "Models", "2026-06"),
        (20, "lab/demo-fr.ipynb", "[3]", "2026-10-14"),
        (21, "content/sec/a.md", "Prices", "2026-11-01"),
    ]
    assert facts.facts[1].fact == "The `pipe | tee` call is in pandas 3.0."
    assert facts.facts[2].source == "the vendor's pricing page"
    assert list_problems(settings, None, today=TODAY) == []
    assert "review-facts-list" in CHECKS
    assert "review-facts-list" not in OPT_IN


def test_the_fiche_and_the_findings_dont_read_the_list(listed: Path) -> None:
    text = REPORT_BODY + ROWS
    grammar = GlobalSettings.from_yaml(listed).review.findings
    assert grammar is not None

    assert "Dated facts" not in fiche(text, grammar.heading)
    found = parse(text, grammar, "r.md")
    assert [f.id for f in found.findings] == ["E1"]
    assert found.findings[0].end == 11
    assert found.problems == ()
    compacted, _ = compact(text, grammar, "r.md")
    assert compacted.endswith(HEADER + ROWS)


def test_a_report_without_a_list_is_valid(listed: Path) -> None:
    _write(listed / "reviews" / "sections" / "sec.md", "# Sec\n\n## Findings\n")
    settings = GlobalSettings.from_yaml(listed)

    assert list_problems(settings, None, today=TODAY) == []
    (facts,) = dated_facts(settings, today=TODAY)
    assert (facts.listed, facts.facts) == (False, ())


def test_the_list_check_names_each_fix(listed: Path) -> None:
    bad = (
        "| a.md | Models | Too short. | 2026-06 | memory |\n"
        "| a.md | Models | A fact with no source given. | 2026-06 |  |\n"
        "| a.md | Models | A fact with a date to come. | 2027-01 | a page |\n"
        "| a.md | Models | A fact with no real date. | June 2026 | a page |\n"
        "| gone.md | Models | A fact about a file since renamed. | 2026-06 | a page |\n"
        "| a.md | Models | A row | with six cells | 2026-06 | a page |\n"
        "- a.md: a fact written as an item\n"
    )
    _write(listed / "reviews" / "sections" / "sec.md", REPORT_BODY + bad)
    _write(
        listed / "reviews" / "decks" / "d.md",
        "# D\n\n## Findings\n\n## Dated facts\n\n" + HEADER,
    )
    settings = GlobalSettings.from_yaml(listed)

    problems = list_problems(settings, None, today=TODAY)

    assert problems[0].startswith("reviews/decks/d.md:5: a list of dated facts")
    report = [p.removeprefix("reviews/sections/sec.md:") for p in problems[1:]]
    assert report[0].startswith("19: « Too short. » doesn't state a fact")
    assert report[1] == (
        "20: empty source cell: fill it (the check of the facts reads this row alone)"
    )
    assert report[2].startswith("21: « 2027-01 » is to come: write the day")
    assert report[3].startswith("22: « June 2026 » is no date")
    assert report[4].startswith("23: no file « gone.md » under content/sec/")
    assert report[5].startswith("24: 6 cells, where a row has 5")
    assert report[6].startswith("25: a list item in the list of dated facts")
    assert len(report) == 7
    # The facts' check reads the rows of a well-formed form only.
    (facts,) = dated_facts(settings, today=TODAY)
    assert [f.line for f in facts.facts] == [23]


def test_the_list_comes_after_the_findings_in_a_section_of_its_own(
    listed: Path,
) -> None:
    before = "# Sec\n\n## Dated facts\n\n" + HEADER + "\n## Findings\n"
    inside = "# Sec\n\n## Findings\n\n### Dated facts\n\n" + HEADER
    twice = REPORT_BODY + "\n## Dated facts\n\n" + HEADER
    no_delimiter = "# Sec\n\n## Findings\n\n## Dated facts\n\n" + HEADER.replace(
        "---", "x"
    )
    problems = {}
    for name, text in [
        ("before", before),
        ("inside", inside),
        ("twice", twice),
        ("no-delimiter", no_delimiter),
    ]:
        _write(listed / "reviews" / "sections" / f"{name}.md", text)
    settings = GlobalSettings.from_yaml(listed)
    for problem in list_problems(settings, None, today=TODAY):
        name = problem.split("/")[-1].split(".md")[0]
        problems.setdefault(name, []).append(problem.split(": ", 1)[1])

    assert problems["before"] == [
        "the list of dated facts comes before « Findings »: everything before it "
        "is the report's fiche; move the list after the findings (write « Findings » "
        "first if the report has none)"
    ]
    assert problems["inside"] == [
        "« Dated facts » is a level-3 heading inside the findings: make it level 2, "
        "a section of its own"
    ]
    assert problems["twice"][0].startswith("a second « Dated facts » heading")
    assert problems["no-delimiter"][0].startswith(
        "the table's second row isn't its delimiter row"
    )


def test_without_a_heading_no_list_is_read(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)

    assert list_problems(settings, None) == []
    assert all(not f.listed for f in dated_facts(settings))


########################################################################################
# The command                                                                          #
########################################################################################


def test_cli_prints_a_sections_list_and_when_its_due(listed: Path, capsys: Any) -> None:
    _write(listed / "reviews" / "sections" / "sec.md", REPORT_BODY + ROWS)
    _write(listed / "reviews" / "sections" / "sec" / "sub.md", "# Sub\n")
    _write(listed / "reviews" / "sections" / "other.md", "# Other\n")

    main(("review", "dated-facts", "sec", "--on", "2026-11-30"))
    out = capsys.readouterr().out

    assert out.splitlines()[0] == (
        "reviews/sections/sec.md: due 2027-10; checked 2026-10-01, every 12 "
        "months (by 2027-10-01); 3 facts"
    )
    assert (
        "  l.19   a.md | Models | The largest context window is one million tokens. "
        "| 2026-06 | the model's knowledge\n"
    ) in out
    # Not committed yet: no date.
    assert "reviews/sections/sec/sub.md: not committed yet, no date; no list yet" in out
    assert "other.md" not in out
    assert (
        out.splitlines()[-1]
        == "2 reports, 0 due on 2026-11-30; 1 with a list (3 facts)"
    )

    main(("review", "dated-facts", "--json", "--due", "--on", "2027-10"))
    found = loads(capsys.readouterr().out)
    assert found["on"] == "2027-10-31"
    assert [r["report"] for r in found["reports"]] == ["reviews/sections/sec.md"]
    (report,) = found["reports"]
    assert (report["due_on"], report["deadline"], report["due"]) == (
        "2027-10-01",
        "2027-10-01",
        True,
    )
    assert report["facts"][1] == {
        "line": 20,
        "file": "lab/demo-fr.ipynb",
        "frame": "[3]",
        "fact": "The `pipe | tee` call is in pandas 3.0.",
        "date": "2026-10-14",
        "source": "https://pandas.pydata.org",
    }
    assert found["calendar"] == {"2027-10": {"12": 1}}

    main(("review", "dated-facts", "--calendar"))
    assert capsys.readouterr().out.splitlines() == [
        "month      12 months  total",
        "2027-10            1      1",
    ]


def test_cli_refuses_what_names_no_section(listed: Path, caplog: Any) -> None:
    _write(listed / "reviews" / "sections" / "sec.md", "# Sec\n")

    with raises(SystemExit) as exc_info:
        main(("review", "dated-facts", "nowhere"))
    assert exc_info.value.code == 1
    assert "nowhere is no shared section" in caplog.text

    _write(listed / "content" / "lone" / "b.md", "# B\n")
    with raises(SystemExit):
        main(("review", "dated-facts", "lone"))
    assert "no section report covers lone" in caplog.text
