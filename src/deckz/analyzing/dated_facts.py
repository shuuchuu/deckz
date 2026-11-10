r"""The shared sections' dated facts: their lists, and when they're due for a check.

A shared section's report (`<review.dir>/sections/<section>.md`) states when its
dated facts (versions, prices, the state of the art) were last checked, on a line
starting with `review.dated_facts.line` and followed by the date:

```markdown
State of the art checked on 2026-10-23, against the vendors' release notes.
```

Without one, the day the report was added counts (the author date of the commit
adding it under `<review.dir>/sections/`, following renames there).

**When they're due.** The rule is the section's delay
(`review.dated_facts.sections`' for the longest section path matching it, else
`review.dated_facts.months`): the facts must be checked again before `checked`
plus that many months, their *deadline*. Left there, every report written in the
same weeks falls due the same month. So each report is given a month of its own
(`schedule`), its *due month*, among the months after the one it was checked in
and up to its deadline's: the reports of one delay are spread so that no month
gets more than `ceil(n / months)` of their `n`, as late as that allows, ties
broken by path. A report is never due after its deadline: the spreading only
brings a check forward (by up to `months - 1` months, for the first cycle of
reports written together), never back, as a fact checked late is worse than one
checked a month early. Once each report is checked in its month, its next
deadline falls in that same month `months` later, which is then its due month:
the spreading holds with no more advance. The months are judged from the
reports alone, never from today, so a verdict changes only as days pass or as
reports change. A time-based verdict changes with no commit, so its check
(`review-dated-facts`) is opt-in (`content_checks.OPT_IN`).

**The list.** With `review.dated_facts.heading` set, a section report lists its
dated facts under that heading, after the findings (`review.findings.heading`,
at its level or above), so that neither its fiche (`deckz review fiche`, all
that comes before the findings) nor its findings read it, and a check of the
facts reads this list instead of the content files. One table, a row per fact,
each row standing on its own:

```markdown
## Dated facts

| File | Frame | Fact | As of | Source |
| --- | --- | --- | --- | --- |
| `rag.md` | Chunks | An LLM may write each chunk's context. | 2024-09 | a blog |
```

The columns, by position (the header row's words are the repository's): the
file (relative to the section's content directory, its notebooks directory or
the repository), the frame's title (or a notebook's cell, `[3]`), the fact in
full, the day (`YYYY-MM-DD`) or month (`YYYY-MM`) its source states it as of,
and the source (a URL, a document, the model's knowledge). A `|` inside a cell
is written `\|`. The `review-facts-list` check (blocking) fails on a list
before the findings, in another kind of report, a list item instead of a row, a
row without five cells, an empty cell, a date that isn't one or is to come, a
file that doesn't exist, and a fact of fewer than four words. A report without
a list is valid: its next check writes it.
"""

import calendar
import re
import subprocess
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from math import ceil
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from .findings import _BREAK, _FENCE, _HEADING, _ITEM, _body_start
from .review import SECTIONS_DIR, report_kind, report_paths, reports_among, review_dir

if TYPE_CHECKING:
    from ..configuring.settings import DatedFactsSettings, GlobalSettings

COLUMNS = ("file", "frame", "fact", "date", "source")
"""A list row's cells, in order."""
_MIN_WORDS = 4
"""The fewest words a fact states itself in."""
_AS_OF = re.compile(r"(\d{4})-(\d{2})(?:-(\d{2}))?")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_DELIMITER = re.compile(r":?-+:?")


@dataclass(frozen=True)
class FactLine:
    """A row of a section report's list of dated facts."""

    line: int
    """Its line in the report (from 1)."""
    file: str
    """As written, its backticks removed."""
    frame: str
    fact: str
    date: str
    """As written: `YYYY-MM-DD` or `YYYY-MM`."""
    source: str


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
    due_on: date | None = None
    """The first day of its due month (`schedule`), on or before `deadline`; \
    None when `checked` is."""
    facts: tuple[FactLine, ...] = ()
    """Its list, in the report's order; empty when it has none."""
    listed: bool = False
    """Whether it has a list (`review.dated_facts.heading`), even an empty one."""

    @property
    def deadline(self) -> date | None:
        """The latest day the rule allows: `months` after `checked`."""
        return None if self.checked is None else add_months(self.checked, self.months)

    def due(self, today: date) -> bool:
        """Whether its facts are due on `today`: its due month has begun.

        Returns:
            True if so.
        """
        return self.due_on is not None and self.due_on <= today


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


def _month(day: date) -> int:
    return day.year * 12 + day.month - 1


def _first_day(month: int) -> date:
    return date(month // 12, month % 12 + 1, 1)


def schedule(found: Sequence[DatedFacts]) -> dict[str, date]:
    """Each report's due month: its deadline's, unless spreading brings it forward.

    The reports of each delay (`months`) are placed one after another, the
    latest deadline first, ties by path, each in the latest month that is
    after the month it was checked in, no later than its deadline's, and
    holds fewer than `ceil(n / months)` of the `n` reports of that delay;
    in its deadline's month when every such month is full. Placing the
    latest deadlines first leaves the earlier months to the reports that
    can't go later: no report is brought forward more than the cap needs.

    Args:
        found: The reports, `checked` and `months` read.

    Returns:
        The first day of each report's due month, by report; none for a \
        report whose `checked` is None.
    """
    groups: dict[int, list[DatedFacts]] = defaultdict(list)
    for facts in found:
        if facts.checked is not None:
            groups[facts.months].append(facts)
    due: dict[str, date] = {}
    for months, group in groups.items():
        cap = ceil(len(group) / months)
        load: dict[int, int] = defaultdict(int)
        windows = []
        for facts in group:
            assert facts.checked is not None
            first = _month(facts.checked) + 1
            windows.append((first + months - 1, first, facts.report))
        # Latest deadline first; ties by path.
        windows.sort(key=lambda w: (-w[0], w[2]))
        for last, first, report in windows:
            month = next((m for m in range(last, first - 1, -1) if load[m] < cap), last)
            load[month] += 1
            due[report] = _first_day(month)
    return due


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


########################################################################################
# The list                                                                             #
########################################################################################


@dataclass(frozen=True)
class _Heading:
    index: int
    level: int
    title: str


@dataclass(frozen=True)
class FactList:
    """A report's list of dated facts, as read."""

    rows: tuple[FactLine, ...]
    """Its well-formed rows, in order: those `problems` names are left out."""
    listed: bool
    """Whether the report has the list's heading."""
    problems: tuple[tuple[int, str], ...]
    """What breaks its form: a line (from 1) and what to do, the report's \
    path not written yet."""


def _headings(lines: Sequence[str], start: int) -> list[_Heading]:
    # The headings after the front matter, outside code blocks.
    found = []
    fence: str | None = None
    for index in range(start, len(lines)):
        line = lines[index]
        if fence is not None:
            stripped = line.strip()
            if stripped.startswith(fence) and not stripped.strip(fence[0]):
                fence = None
        elif opening := _FENCE.match(line):
            fence = opening.group(1)
        elif match := _HEADING.match(line):
            found.append(
                _Heading(index, len(match.group(1)), (match.group(2) or "").strip())
            )
    return found


def _cells(line: str) -> list[str]:
    inner = line.strip()
    inner = inner.removeprefix("|")
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [cell.strip().replace("\\|", "|") for cell in _CELL_SPLIT.split(inner)]


def _date_problem(text: str, today: date) -> str | None:
    match = _AS_OF.fullmatch(text)
    fix = "write the day (YYYY-MM-DD) or the month (YYYY-MM) its source states it as of"
    if match is None:
        return f"« {text} » is no date: {fix}"
    year, month, day = (int(g) if g else None for g in match.groups())
    assert year is not None and month is not None
    try:
        as_of = date(year, month, day or 1)
    except ValueError:
        return f"« {text} » is no date: {fix}"
    if (day is not None and as_of > today) or (
        day is None and (year, month) > (today.year, today.month)
    ):
        return f"« {text} » is to come: {fix}"
    return None


def _file_problem(settings: "GlobalSettings", section: str, written: str) -> str | None:
    paths = settings.paths
    candidates = [
        paths.content_dir / section / written,
        paths.labs_notebooks_dir / section / written,
        paths.git_dir / written,
    ]
    if any(path.is_file() for path in candidates):
        return None
    content = (paths.content_dir / section).relative_to(paths.git_dir).as_posix()
    return (
        f"no file « {written} » under {content}/, the section's notebooks or the "
        "repository: write its path from one of them (renamed?), or remove the "
        "row if the file is gone"
    )


def read_list(
    text: str,
    heading: str,
    findings_heading: str | None,
    *,
    is_section: bool = True,
    settings: "GlobalSettings | None" = None,
    section: str = "",
    today: date | None = None,
) -> FactList:
    """Read a report's list of dated facts, and what breaks its form.

    Args:
        text: The report.
        heading: The list's heading text (`review.dated_facts.heading`).
        findings_heading: The findings heading's text, which the list comes \
            after (`review.findings.heading`); None if there's none.
        is_section: Whether it's a shared section's report, the only kind \
            whose list is read.
        settings: The repository's settings, to check each row's file \
            exists; None to leave the files alone.
        section: The report's section, from which a row's file may be given.
        today: The day a date can't be after.

    Returns:
        The list.
    """
    today = today or date.today()
    lines = text.splitlines()
    headings = _headings(lines, _body_start(lines))
    mine = [h for h in headings if h.title == heading]
    if not mine:
        return FactList((), False, ())
    problems: list[tuple[int, str]] = []
    first = mine[0]
    problems.extend(
        (
            h.index + 1,
            f"a second « {heading} » heading: merge its rows into the "
            f"list of line {first.index + 1}",
        )
        for h in mine[1:]
    )
    if not is_section:
        problems.append(
            (
                first.index + 1,
                f"a list of dated facts (« {heading} ») outside a shared section's "
                "report: only those are read; move its rows to the report of the "
                "section their files belong to",
            )
        )
    if findings_heading is not None:
        findings = next((h for h in headings if h.title == findings_heading), None)
        if findings is None or findings.index > first.index:
            problems.append(
                (
                    first.index + 1,
                    f"the list of dated facts comes before « {findings_heading} »: "
                    "everything before it is the report's fiche; move the list "
                    f"after the findings (write « {findings_heading} » first if "
                    "the report has none)",
                )
            )
        elif first.level > findings.level:
            problems.append(
                (
                    first.index + 1,
                    f"« {heading} » is a level-{first.level} heading inside the "
                    f"findings: make it level {findings.level}, a section of its "
                    "own",
                )
            )
    end = next(
        (h.index for h in headings if h.index > first.index and h.level <= first.level),
        len(lines),
    )
    rows, row_problems = _rows(lines, first.index + 1, end, today)
    problems.extend(row_problems)
    kept = []
    for row in rows:
        if settings is not None and (
            problem := _file_problem(settings, section, row.file)
        ):
            problems.append((row.line, problem))
        else:
            kept.append(row)
    return FactList(tuple(kept), True, tuple(sorted(problems)))


def _table_lines(
    lines: Sequence[str], start: int, end: int
) -> Iterator[tuple[int, str, int]]:
    # The lines between `start` and `end` outside code blocks: each table
    # row with its line number and its rank in its table (from 1), and each
    # other line with rank 0.
    rank = 0
    fence: str | None = None
    for index in range(start, end):
        line = lines[index]
        if fence is not None:
            stripped = line.strip()
            if stripped.startswith(fence) and not stripped.strip(fence[0]):
                fence = None
        elif opening := _FENCE.match(line):
            fence, rank = opening.group(1), 0
        elif line.lstrip().startswith("|"):
            rank += 1
            yield index + 1, line, rank
        else:
            rank = 0
            yield index + 1, line, rank


def _rows(
    lines: Sequence[str], start: int, end: int, today: date
) -> tuple[list[FactLine], list[tuple[int, str]]]:
    # The table rows between `start` and `end`, each table's first two being
    # its header and delimiter.
    rows: list[FactLine] = []
    problems: list[tuple[int, str]] = []
    for number, line, rank in _table_lines(lines, start, end):
        if rank == 0:
            if _ITEM.match(line) and not _BREAK.match(line):
                problems.append(
                    (
                        number,
                        "a list item in the list of dated facts: write each fact as "
                        f"a row of its table, | {' | '.join(COLUMNS)} |",
                    )
                )
            continue
        cells = _cells(line)
        if len(cells) != len(COLUMNS):
            problems.append(
                (
                    number,
                    f"{len(cells)} cells, where a row has {len(COLUMNS)}: "
                    f"{', '.join(COLUMNS)} (a `|` inside a cell is written `\\|`)",
                )
            )
        elif rank == 2 and not all(_DELIMITER.fullmatch(c) for c in cells):
            problems.append(
                (
                    number,
                    "the table's second row isn't its delimiter row: write "
                    "`| --- | --- | --- | --- | --- |` under its header",
                )
            )
        elif rank > 2:
            row = _row(number, cells, today)
            if isinstance(row, FactLine):
                rows.append(row)
            else:
                problems.extend((number, problem) for problem in row)
    return rows, problems


def _row(number: int, cells: Sequence[str], today: date) -> FactLine | list[str]:
    values = dict(zip(COLUMNS, cells, strict=True))
    values["file"] = values["file"].strip("`").strip()
    problems = [
        f"empty {column} cell: fill it (the check of the facts reads this row alone)"
        for column, value in values.items()
        if not value
    ]
    if values["date"] and (problem := _date_problem(values["date"], today)):
        problems.append(problem)
    if values["fact"] and len(values["fact"].split()) < _MIN_WORDS:
        problems.append(
            f"« {values['fact']} » doesn't state a fact: write it in full, as "
            "the check of the facts reads this row, not the file"
        )
    if problems:
        return problems
    return FactLine(number, **values)


########################################################################################
# Reports                                                                              #
########################################################################################


def _section_reports(settings: "GlobalSettings") -> list[Path]:
    sections = review_dir(settings) / SECTIONS_DIR
    return [
        path
        for path in report_paths(settings)
        if path.is_relative_to(sections)
        and (kind := report_kind(settings, path)) is not None
        and kind[0] == "section"
    ]


def dated_facts(
    settings: "GlobalSettings",
    paths: Iterable[Path] | None = None,
    today: date | None = None,
) -> list[DatedFacts]:
    """Every shared section report's dated facts, their due month and their list.

    Args:
        settings: The repository's settings.
        paths: Only the reports among these (absolute paths); None for all. \
            The due months are those of every report all the same.
        today: The day a list's dates can't be after.

    Returns:
        One per section report, by path; none without `review.dated_facts`.
    """
    grammar = settings.review.dated_facts
    if settings.review.dir is None or grammar is None:
        return []
    git_dir = settings.paths.git_dir
    sections = review_dir(settings) / SECTIONS_DIR
    reports = _section_reports(settings)
    added = _added(git_dir, sections) if reports else {}
    findings = settings.review.findings
    found = []
    for path in reports:
        rel = path.relative_to(git_dir).as_posix()
        section = path.relative_to(sections).with_suffix("").as_posix()
        text = path.read_text(encoding="utf8")
        checked = _checked_on(grammar.line, text)
        source: Literal["line", "added"] | None = "line"
        if checked is None:
            checked = added.get(rel)
            source = None if checked is None else "added"
        listed = (
            read_list(
                text,
                grammar.heading,
                None if findings is None else findings.heading,
                today=today,
            )
            if grammar.heading
            else FactList((), False, ())
        )
        found.append(
            DatedFacts(
                rel,
                section,
                checked,
                source,
                delay(grammar, section),
                facts=listed.rows,
                listed=listed.listed,
            )
        )
    due = schedule(found)
    found = [replace(f, due_on=due.get(f.report)) for f in found]
    if paths is None:
        return found
    wanted = {p.relative_to(git_dir).as_posix() for p in reports_among(settings, paths)}
    return [f for f in found if f.report in wanted]


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
    for facts in dated_facts(settings, paths, today):
        if not facts.due(today):
            continue
        assert facts.due_on is not None
        since = (
            f"last checked on {facts.checked}"
            if facts.source == "line"
            else f"never checked since the report was added on {facts.checked}"
        )
        listing = (
            f"its list: `deckz review dated-facts {facts.report}`"
            if facts.listed
            else "its list, to write as they're checked"
            + (f" (« {grammar.heading} »)" if grammar.heading else "")
        )
        problems.append(
            f"{facts.report}: dated facts due since {facts.due_on:%Y-%m}, {since} "
            f"(every {facts.months} months, at the latest by {facts.deadline}): "
            f"check them ({listing}), then write the day on its `{grammar.line} "
            "YYYY-MM-DD` line"
        )
    return problems


def list_problems(
    settings: "GlobalSettings",
    paths: Iterable[Path] | None,
    today: date | None = None,
) -> list[str]:
    """The `review-facts-list` check: every list of dated facts is well formed.

    Args:
        settings: The repository's settings.
        paths: Only check the reports among these (absolute paths); None for \
            every report.
        today: The day a row's date can't be after.

    Returns:
        The problems, `<report>:<line>: …`; none without \
        `review.dated_facts.heading`.
    """
    grammar = settings.review.dated_facts
    if settings.review.dir is None or grammar is None or not grammar.heading:
        return []
    git_dir = settings.paths.git_dir
    sections = review_dir(settings) / SECTIONS_DIR
    findings = settings.review.findings
    problems = []
    for path in reports_among(settings, paths):
        kind = report_kind(settings, path)
        is_section = kind is not None and kind[0] == "section"
        found = read_list(
            path.read_text(encoding="utf8"),
            grammar.heading,
            None if findings is None else findings.heading,
            is_section=is_section,
            settings=settings,
            section=path.relative_to(sections).with_suffix("").as_posix()
            if is_section
            else "",
            today=today,
        )
        rel = path.relative_to(git_dir).as_posix()
        problems.extend(f"{rel}:{line}: {problem}" for line, problem in found.problems)
    return problems


def due_by_month(found: Iterable[DatedFacts]) -> Mapping[str, Mapping[int, int]]:
    """How many reports fall due each month, by delay: the schedule at a glance.

    Returns:
        `{YYYY-MM: {months: count}}`, by month.
    """
    counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for facts in found:
        if facts.due_on is not None:
            counts[f"{facts.due_on:%Y-%m}"][facts.months] += 1
    return {month: dict(sorted(c.items())) for month, c in sorted(counts.items())}


def _prefix(settings: "GlobalSettings", given: Path) -> str | None:
    # The section path a target stands for, "" for every section; None if
    # it's no section nor section report.
    from contextlib import suppress

    from ..exceptions import ReviewError
    from .review import locate

    sections = review_dir(settings) / SECTIONS_DIR
    content_dir = settings.paths.content_dir
    candidates = [] if given.is_absolute() else [content_dir / given]
    with suppress(ReviewError):  # Outside the repository: not a path then.
        candidates.insert(0, locate(settings, given))
    for candidate in candidates:
        if candidate.is_relative_to(sections):
            relative = candidate.relative_to(sections)
            if relative.suffix == ".md":
                relative = relative.with_suffix("")
            return "" if relative == Path() else relative.as_posix()
        if candidate.is_dir() and candidate.is_relative_to(content_dir):
            relative = candidate.relative_to(content_dir)
            return "" if relative == Path() else relative.as_posix()
    return None


def targeted(
    settings: "GlobalSettings", targets: Sequence[Path], today: date | None = None
) -> list[DatedFacts]:
    """`deckz review dated-facts`: the dated facts of sections or domains.

    Args:
        settings: The repository's settings.
        targets: As given: shared sections (`content/genai`, or `genai`), \
            each standing for its report and those of its subsections, or \
            reports and directories under `<review.dir>/sections/`; none for \
            every section report.
        today: The day a list's dates can't be after.

    Returns:
        Their reports' dated facts, by section.

    Raises:
        ReviewError: If `review.dir` or `review.dated_facts` is unset, or a \
            target is no section, or no section report covers it.
    """
    from ..exceptions import ReviewError

    directory = review_dir(settings)
    if settings.review.dated_facts is None:
        msg = (
            "no dated facts: set `review.dated_facts` in deckz.yml, e.g. "
            "`dated_facts: {line: State of the art checked on, months: 12, "
            "heading: Dated facts}` under `review`"
        )
        raise ReviewError(msg)
    # By section, a section before its subsections.
    found = sorted(
        dated_facts(settings, today=today),
        key=lambda f: PurePosixPath(f.section).parts,
    )
    if not targets:
        return found
    git_dir = settings.paths.git_dir
    sections = (directory / SECTIONS_DIR).relative_to(git_dir).as_posix()
    content = settings.paths.content_dir.relative_to(git_dir).as_posix()
    wanted: dict[str, None] = {}
    for given in targets:
        prefix = _prefix(settings, given)
        if prefix is None:
            msg = (
                f"{given} is no shared section (e.g. {content}/<section>, or "
                f"<section>) nor a section report (under {sections})"
            )
            raise ReviewError(msg)
        matched = [
            f.report
            for f in found
            if not prefix or f.section == prefix or f.section.startswith(f"{prefix}/")
        ]
        if not matched:
            msg = (
                f"no section report covers {given}: a review writes "
                f"{sections}/{prefix}.md"
            )
            raise ReviewError(msg)
        wanted.update(dict.fromkeys(matched))
    return [f for f in found if f.report in wanted]
