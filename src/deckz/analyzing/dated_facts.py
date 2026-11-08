"""When the shared sections' dated facts are due for a check: `review-dated-facts`.

A shared section's report (`<review.dir>/sections/<section>.md`) states when its
dated facts (versions, prices, the state of the art) were last checked, on a line
starting with `review.dated_facts.line` and followed by the date:

```markdown
State of the art checked on 2026-10-23, against the vendors' release notes.
```

Without one, the day the report was added counts (the author date of the commit
adding it under `<review.dir>/sections/`, following renames there). The facts are
due once that date is older than the section's delay: `review.dated_facts.sections`'
for the longest section path matching it, else `review.dated_facts.months`. A
time-based verdict changes with no commit, so its check is opt-in
(`content_checks.OPT_IN`).
"""

import calendar
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from .review import SECTIONS_DIR, report_kind, reports_among, review_dir

if TYPE_CHECKING:
    from ..configuring.settings import DatedFactsSettings, GlobalSettings


@dataclass(frozen=True)
class DatedFacts:
    """A section report's dated facts: when they were checked, when they're due."""

    report: str
    """Relative to the repository."""
    section: str
    """Its section, relative to the shared content directory."""
    checked: date | None
    """The day its facts were last checked; None if it says nothing and isn't \
    committed yet."""
    source: Literal["line", "added"] | None
    """Where `checked` comes from: the report's line, or the day it was added."""
    months: int
    """Its section's delay."""

    @property
    def due_on(self) -> date | None:
        """The day its facts are due: `months` after `checked`."""
        return None if self.checked is None else add_months(self.checked, self.months)

    def due(self, today: date) -> bool:
        """Whether its facts are due on `today`.

        Returns:
            True if so.
        """
        return self.due_on is not None and self.due_on < today


def add_months(day: date, months: int) -> date:
    """`day` plus `months`, on the month's last day if it has fewer days.

    Returns:
        The day.
    """
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def delay(grammar: "DatedFactsSettings", section: str) -> int:
    """A section's delay, in months.

    Returns:
        That of the longest path of `grammar.sections` that is the section or \
        one of its parents, else `grammar.months`.
    """
    pure = PurePosixPath(section)
    matching = [
        (len(PurePosixPath(prefix).parts), months)
        for prefix, months in grammar.sections.items()
        if pure == PurePosixPath(prefix) or pure.is_relative_to(prefix)
    ]
    return max(matching)[1] if matching else grammar.months


def _checked_on(line: str, text: str) -> date | None:
    # The latest date the report's lines starting with `line` give.
    pattern = re.compile(rf"^{re.escape(line)}\s+(\d{{4}}-\d{{2}}-\d{{2}})", re.M)
    found = []
    for match in pattern.finditer(text):
        try:
            found.append(date.fromisoformat(match.group(1)))
        except ValueError:
            continue
    return max(found, default=None)


def _added(git_dir: Path, directory: Path) -> dict[str, date]:
    # The day each file under `directory` was added there, following the
    # renames inside it, by path relative to the repository.
    out = subprocess.run(
        [
            "git",
            "-C",
            str(git_dir),
            "log",
            "--reverse",
            "-M",
            "--name-status",
            "--format=%x00%as",
            "--",
            directory.relative_to(git_dir).as_posix(),
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    added: dict[str, date] = {}
    day = None
    for line in out.splitlines():
        if line.startswith("\0"):
            day = date.fromisoformat(line[1:].strip())
            continue
        fields = line.split("\t")
        if day is None or len(fields) < 2:
            continue
        status = fields[0][:1]
        if status == "A":
            added.setdefault(fields[1], day)
        elif status in ("R", "C") and len(fields) == 3:
            added[fields[2]] = added.get(fields[1], day)
            if status == "R":
                added.pop(fields[1], None)
        elif status == "D":
            added.pop(fields[1], None)
    return added


def dated_facts(
    settings: "GlobalSettings", paths: Iterable[Path] | None = None
) -> list[DatedFacts]:
    """Every shared section report's dated facts.

    Args:
        settings: The repository's settings.
        paths: Only the reports among these (absolute paths); None for all.

    Returns:
        One per section report, by path; none without `review.dated_facts`.
    """
    grammar = settings.review.dated_facts
    if settings.review.dir is None or grammar is None:
        return []
    git_dir = settings.paths.git_dir
    sections = review_dir(settings) / SECTIONS_DIR
    reports = [
        path
        for path in reports_among(settings, paths)
        if path.is_relative_to(sections)
        and (kind := report_kind(settings, path)) is not None
        and kind[0] == "section"
    ]
    added = _added(git_dir, sections) if reports else {}
    found = []
    for path in reports:
        rel = path.relative_to(git_dir).as_posix()
        section = path.relative_to(sections).with_suffix("").as_posix()
        checked = _checked_on(grammar.line, path.read_text(encoding="utf8"))
        source: Literal["line", "added"] | None = "line"
        if checked is None:
            checked = added.get(rel)
            source = None if checked is None else "added"
        found.append(DatedFacts(rel, section, checked, source, delay(grammar, section)))
    return found


def dated_facts_problems(
    settings: "GlobalSettings",
    paths: Iterable[Path] | None,
    today: date | None = None,
) -> list[str]:
    """The `review-dated-facts` check: no section report's dated facts are due.

    Returns:
        One line per report whose facts are due, with the fix.
    """
    grammar = settings.review.dated_facts
    if grammar is None:
        return []
    today = today or date.today()
    problems = []
    for facts in dated_facts(settings, paths):
        if not facts.due(today):
            continue
        since = (
            f"last checked on {facts.checked}"
            if facts.source == "line"
            else f"never checked since the report was added on {facts.checked}"
        )
        problems.append(
            f"{facts.report}: dated facts {since}, more than {facts.months} months "
            f"ago: check them, then write the day on its `{grammar.line} "
            "YYYY-MM-DD` line"
        )
    return problems
