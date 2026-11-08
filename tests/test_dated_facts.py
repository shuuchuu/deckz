import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from pytest import fixture

from deckz.analyzing.content_checks import OPT_IN
from deckz.analyzing.dated_facts import add_months, dated_facts, dated_facts_problems
from deckz.configuring.settings import GlobalSettings

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

    assert dated_facts_problems(settings, None, today=date(2026, 7, 10)) == []
    problems = dated_facts_problems(settings, None, today=date(2026, 7, 11))
    assert len(problems) == 1
    assert problems[0].startswith("reviews/sections/fast/tool.md: dated facts never")
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
