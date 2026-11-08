"""The maintenance dashboard, `deckz dashboard`: what of the repository needs care.

A read-only aggregate of what deckz already measures, recomputing none of it:
the review registry (`analyzing.review`: `ranking`, `deck_review`), the
findings of its reports (`analyzing.findings`), their dated facts
(`analyzing.dated_facts`), the course notes coverage
(`course_notes.repository_coverage`) and, when the calendar can be read, each
deck's sessions (`sessions.sessions_report`, never logging in).

A deck is up to date at five levels, each judged on its own (`DeckRow`):
its content files are fresh, its labs are fresh (the files other than content
the reports covering it record, `DeckReview.others`), its deck pass holds, no
covering section report has dated facts due, and no covering report has an
open finding (the `review.findings.critical` rubrics counted apart; the
reports recording its course notes chapters cover it too). A level
with nothing to judge, no notebook recorded or no report covering the deck, is
neither met nor failed (`ok` is None).

An INTRA deck (one whose `deck.yml` claims a calendar engagement) is *past*
when the calendar shows no upcoming engagement for it, or, the calendar
unreadable, when its claimed start is more than `PAST_INTRA_DAYS` ago: past
decks are left out unless asked for.

Each row names the file to open about it (`Opens`), studioz's page opening it
in its editor: a deck its first chapter due under a rule, else its deck
report; a section the first of its chapters due, else the chapter of its
first file needing care, else that file's report, else the file itself (a
section needing care for its findings or dated facts alone: the report
holding them).
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .analyzing.dated_facts import DatedFacts
    from .analyzing.findings import ReportFindings
    from .analyzing.review import (
        DeckPass,
        DeckReview,
        FileReview,
        RankedSection,
        State,
    )
    from .configuring.settings import GlobalSettings, ReviewRule
    from .course_notes import ChapterEntry, DeckCoverage
    from .sessions import CalendarEngagement

PAST_INTRA_DAYS = 31
"""Without the calendar, an INTRA deck whose claimed start is older is past."""

SectionState = Literal["fresh", "due", "partial", "stale", "none"]

OpensWhy = Literal["chapter_due", "chapter", "report", "file"]
"""Why a row opens its file: a chapter due under a rule, the chapter of a \
file needing care, a report, a content file with neither."""


########################################################################################
# Levels                                                                               #
########################################################################################


@dataclass(frozen=True)
class FilesLevel:
    """A level judged on files' review states: a deck's content, or its labs."""

    files: tuple["FileReview", ...]

    @property
    def counts(self) -> dict["State", int]:
        """How many files are in each state, the states with none left out."""
        return dict(Counter(review.state for review in self.files))

    @property
    def to_review(self) -> int:
        """How many files aren't fresh."""
        return sum(review.state != "fresh" for review in self.files)

    @property
    def ok(self) -> bool | None:
        """Every file fresh; None when there is no file."""
        return None if not self.files else self.to_review == 0


@dataclass(frozen=True)
class FindingsLevel:
    """The findings of the reports covering a deck or a section."""

    reports: tuple[str, ...]
    """The reports read, relative to the repository."""
    open: Mapping[str, int]
    """Open findings by rubric, every rubric of the grammar in its order."""
    critical: int
    """Open findings of the `review.findings.critical` rubrics."""

    @property
    def total(self) -> int:
        """Open findings, every rubric's."""
        return sum(self.open.values())

    @property
    def ok(self) -> bool | None:
        """No open finding; None when no report covers it."""
        return None if not self.reports else self.total == 0


@dataclass(frozen=True)
class FactsLevel:
    """The dated facts of the section reports covering a deck or a section."""

    facts: tuple["DatedFacts", ...]
    due: tuple[str, ...]
    """The reports whose facts are due today."""

    @property
    def ok(self) -> bool | None:
        """No facts due; None when no section report covers it."""
        return None if not self.facts else not self.due


@dataclass(frozen=True)
class Opens:
    """The file to open about a row, existing."""

    file: str
    """Relative to the repository."""
    why: OpensWhy


########################################################################################
# Rows                                                                                 #
########################################################################################


@dataclass(frozen=True)
class SectionRow:
    """A shared section some deck uses."""

    ranked: "RankedSection"
    """Its files, score and reports, from `review.ranking`."""
    decks: tuple[str, ...]
    """The decks including one of its files, by path."""
    state: SectionState
    findings: FindingsLevel | None
    """None without a findings grammar (`review.findings`)."""
    dated_facts: FactsLevel
    opens: Opens | None = None
    """None when no file applies (no chapter, report nor file left)."""

    @property
    def section(self) -> str:
        """Its path, relative to the shared content directory."""
        return self.ranked.section

    @property
    def needs_care(self) -> bool:
        """Not fresh, an open finding, or its dated facts due."""
        return (
            self.state != "fresh"
            or (self.findings is not None and self.findings.total > 0)
            or bool(self.dated_facts.due)
        )


@dataclass(frozen=True)
class DeckRow:
    """A deck, its five levels, its course notes and its sessions."""

    deck: str
    """Its directory, relative to the repository."""
    frames: int
    """Its content files' frames to review (`DeckReview.frames`)."""
    content: FilesLevel
    labs: FilesLevel
    deck_pass: "DeckPass"
    dated_facts: FactsLevel
    findings: FindingsLevel | None
    """None without a findings grammar (`review.findings`)."""
    course_notes: "DeckCoverage | None"
    chapters_due: tuple[tuple["ReviewRule", int], ...]
    """Its written French chapters due, per rule having any."""
    intra: bool
    """Its `deck.yml` claims a calendar engagement."""
    sessions: tuple["CalendarEngagement", ...] | None
    """By start; None when the calendar can't be read."""
    next_session: "CalendarEngagement | None"
    """Its first engagement not over yet (one ending today isn't)."""
    past: bool
    opens: Opens | None = None
    """None when it has no chapter due and no deck report: its deck page."""


########################################################################################
# Totals                                                                               #
########################################################################################


@dataclass(frozen=True)
class FindingsTotals:
    open: Mapping[str, int]
    """By rubric, every rubric of the grammar in its order."""
    critical: int
    done: int
    refused: int
    none: int
    """Findings with no outcome (the `review-findings` check fails)."""
    reports_with_open: int


@dataclass(frozen=True)
class RuleTotal:
    rule: "ReviewRule"
    due: int
    """The files due for it (fresh or stale): sections' files, decks' labs, \
    French chapters."""


@dataclass(frozen=True)
class Totals:
    sections: Mapping[SectionState, int]
    """Every shared section some deck uses, by state, every state."""
    files: Mapping["State", int]
    """Their files, by state, every state."""
    findings: FindingsTotals | None
    course_notes: Sequence["ChapterEntry"]
    """Every content file of the decks once (`Coverage.files`)."""
    complete_decks: int
    """Decks whose every file needing a chapter has one."""
    rules: tuple[RuleTotal, ...]
    dated_facts_due: tuple[str, ...]
    """The section reports whose facts are due today."""


@dataclass(frozen=True)
class SessionsInfo:
    """Whether the calendar was read, and how."""

    available: bool
    why: str | None = None
    """Why it can't be read (`CalendarError`'s message)."""
    fetched_at: datetime | None = None
    note: str | None = None
    unmatched: int = 0
    """Sessions no deck matches (`deckz sessions` lists them)."""
    problems: int = 0


@dataclass(frozen=True)
class Dashboard:
    today: date
    totals: Totals
    sections: tuple[SectionRow, ...]
    """By `ranking`'s order: score, decks, path."""
    decks: tuple[DeckRow, ...]
    """By next session, then frames to review, then path; past INTRA \
    decks left out unless asked for."""
    left_out: tuple[str, ...]
    """The past INTRA decks left out."""
    sessions: SessionsInfo
    problems: tuple[str, ...]
    """The reports that couldn't be read, the findings breaking the grammar."""


########################################################################################
# Building                                                                             #
########################################################################################


def _section_state(files: Sequence["FileReview"]) -> SectionState:
    states = {review.state for review in files}
    if states <= {"unreviewed"}:
        return "none"
    if states & {"stale", "deleted"}:
        return "stale"
    if "unreviewed" in states:
        return "partial"
    return "due" if "due" in states else "fresh"


def _findings_level(
    settings: "GlobalSettings",
    by_report: Mapping[str, "ReportFindings"] | None,
    reports: Iterable[str],
) -> FindingsLevel | None:
    if by_report is None or settings.review.findings is None:
        return None
    grammar = settings.review.findings
    read = tuple(sorted(r for r in set(reports) if r in by_report))
    open_ = {
        rubric: sum(by_report[r].count("open", rubric) for r in read)
        for rubric in grammar.rubrics
    }
    return FindingsLevel(read, open_, sum(open_[rubric] for rubric in grammar.critical))


def _facts_level(
    facts: Mapping[str, "DatedFacts"], reports: Iterable[str], today: date
) -> FactsLevel:
    found = tuple(facts[r] for r in sorted(set(reports)) if r in facts)
    return FactsLevel(found, tuple(f.report for f in found if f.due(today)))


def _findings_totals(
    settings: "GlobalSettings", by_report: Mapping[str, "ReportFindings"] | None
) -> FindingsTotals | None:
    if by_report is None or settings.review.findings is None:
        return None
    grammar = settings.review.findings
    reports = list(by_report.values())
    open_ = {
        rubric: sum(r.count("open", rubric) for r in reports)
        for rubric in grammar.rubrics
    }
    return FindingsTotals(
        open_,
        sum(open_[rubric] for rubric in grammar.critical),
        sum(r.count("done") for r in reports),
        sum(r.count("refused") for r in reports),
        sum(r.count(None) for r in reports),
        sum(r.count("open") > 0 for r in reports),
    )


def _rules_due(
    settings: "GlobalSettings", files: Iterable["FileReview"]
) -> tuple[tuple["ReviewRule", int], ...]:
    due = Counter(rule for review in files for rule in review.due)
    return tuple((rule, due[rule]) for rule in settings.review.rules if due[rule])


def _deck_opens(settings: "GlobalSettings", review: "DeckReview") -> Opens | None:
    due = next((chapter for chapter in review.chapters if chapter.due), None)
    if due is not None:
        return Opens(due.path, "chapter_due")
    report = review.deck_pass.report
    if (settings.paths.git_dir / report).is_file():
        return Opens(report, "report")
    return None


def _chapter_of(settings: "GlobalSettings", review: "FileReview") -> str | None:
    # The written French chapter of a shared content file, relative to the repo.
    from .course_notes import chapter_path, covering

    paths = settings.paths
    content = PurePosixPath(paths.content_dir.relative_to(paths.git_dir).as_posix())
    file = PurePosixPath(review.path)
    if not file.is_relative_to(content):
        return None
    chapter = chapter_path(
        settings,
        covering(settings, file.relative_to(content).with_suffix("").as_posix()),
        "fr",
    )
    return chapter.relative_to(paths.git_dir).as_posix() if chapter.is_file() else None


def _section_opens(
    settings: "GlobalSettings",
    ranked: "RankedSection",
    chapters: Mapping[str, "FileReview"],
    by_report: Mapping[str, "ReportFindings"] | None,
    facts: FactsLevel,
) -> Opens | None:
    written = {review.path: _chapter_of(settings, review) for review in ranked.files}
    for chapter in written.values():
        if chapter is not None and chapter in chapters and chapters[chapter].due:
            return Opens(chapter, "chapter_due")
    first = next((r for r in ranked.files if r.state != "fresh"), None)
    if first is not None:
        if (chapter := written[first.path]) is not None:
            return Opens(chapter, "chapter")
        report = first.report or next(iter(ranked.reports), None)
        if report is not None:
            return Opens(report, "report")
        if (settings.paths.git_dir / first.path).is_file():
            return Opens(first.path, "file")
        return None
    # Fresh: its findings or its dated facts need care, in a report.
    with_open = [
        r
        for r in ranked.reports
        if by_report and r in by_report and by_report[r].count("open")
    ]
    report = next(iter([*with_open, *facts.due, *ranked.reports]), None)
    return None if report is None else Opens(report, "report")


def _is_past(
    claim_start: date | None,
    sessions: Sequence["CalendarEngagement"] | None,
    today: date,
) -> bool:
    if claim_start is None:
        return False
    if sessions is not None:
        return not any(e.end >= today for e in sessions)
    return claim_start < today - timedelta(days=PAST_INTRA_DAYS)


def _read_sessions(
    settings: "GlobalSettings",
    *,
    refresh: bool,
    events_file: Path | None,
    today: date,
) -> tuple[SessionsInfo, Mapping[str, tuple["CalendarEngagement", ...]] | None]:
    from .exceptions import CalendarError
    from .sessions import sessions_report

    try:
        report = sessions_report(
            settings, refresh=refresh, events_file=events_file, today=today
        )
    except CalendarError as error:
        return SessionsInfo(available=False, why=str(error)), None
    calendar = report.calendar
    return (
        SessionsInfo(
            available=True,
            fetched_at=calendar.fetched_at,
            note=calendar.note,
            unmatched=len(report.orphans),
            problems=len(report.problems),
        ),
        {deck.deck.as_posix(): deck.engagements for deck in report.decks},
    )


def dashboard(
    settings: "GlobalSettings",
    *,
    include_past: bool = False,
    refresh: bool = False,
    events_file: Path | None = None,
    today: date | None = None,
) -> Dashboard:
    """`deckz dashboard`: the repository's sections and decks, and the totals.

    Args:
        settings: The repository's settings.
        include_past: Keep the past INTRA decks.
        refresh: Read Google Calendar now, whatever the cache's age.
        events_file: Read the calendar's events from this JSON file instead.
        today: The day the dated facts and sessions are judged on.

    Returns:
        The dashboard. Fails (`review.review_dir`) if `review.dir` is unset,
        and if a deck doesn't parse (as `review.ranking` does).
    """
    from .analyzing.dated_facts import dated_facts
    from .analyzing.findings import findings_status
    from .analyzing.review import (
        all_reports,
        deck_review,
        expand,
        marks_index,
        ranking,
        review_dir,
        review_files,
    )
    from .course_notes import coverage_share, repository_coverage
    from .sessions import read_decks
    from .utils import all_deck_settings

    today = date.today() if today is None else today
    review_dir(settings)
    git_dir = settings.paths.git_dir
    reports, problems = all_reports(settings)
    index = marks_index(git_dir, reports)
    recorded = {report.path for report in reports}

    by_report: dict[str, ReportFindings] | None = None
    if settings.review.findings is not None:
        found = findings_status(settings, [])
        by_report = {r.report: r for r in found.reports}
        problems = [*problems, *(p for p in found.problems if p not in problems)]
    facts = {f.report: f for f in dated_facts(settings)}
    coverage = repository_coverage(settings, git_dir, "fr")
    by_deck_coverage = {d.deck: d for d in coverage.decks}
    sessions, engagements = _read_sessions(
        settings, refresh=refresh, events_file=events_file, today=today
    )
    claims = read_decks(settings).claims

    ranked = ranking(settings, reports, index)
    reviews = sorted(
        (deck_review(deck, reports, index) for deck in all_deck_settings(git_dir)),
        key=lambda r: r.deck,
    )
    section_decks: dict[str, list[str]] = {}
    rows = []
    for review in reviews:
        for section in review.sections:
            section_decks.setdefault(section.section, []).append(review.deck)
        # As `review findings <deck>`: `review.deck_covered_paths`' reports.
        covering = {
            mark.report for f in (*review.content, *review.chapters) for mark in f.marks
        }
        if review.deck_pass.report in recorded:
            covering.add(review.deck_pass.report)
        claim = claims.get(PurePosixPath(review.deck))
        deck_sessions = (
            None if engagements is None else engagements.get(review.deck, ())
        )
        rows.append(
            DeckRow(
                deck=review.deck,
                frames=review.frames,
                content=FilesLevel(review.content),
                labs=FilesLevel(review.others),
                deck_pass=review.deck_pass,
                dated_facts=_facts_level(facts, covering, today),
                findings=_findings_level(settings, by_report, covering),
                course_notes=by_deck_coverage.get(review.deck),
                chapters_due=_rules_due(settings, review.chapters),
                intra=claim is not None,
                sessions=deck_sessions,
                next_session=next(
                    (e for e in deck_sessions or () if e.end >= today), None
                ),
                past=_is_past(
                    None if claim is None else claim.start, deck_sessions, today
                ),
                opens=_deck_opens(settings, review),
            )
        )

    def order(row: DeckRow) -> tuple:
        upcoming = row.next_session
        if upcoming is not None:
            return (0, upcoming.start.toordinal(), row.deck)
        return (1, -row.frames, row.deck)

    rows.sort(key=order)
    shown = tuple(row for row in rows if include_past or not row.past)
    left_out = tuple(row.deck for row in rows if row.past and not include_past)

    chapters_dir = settings.paths.course_notes_dir
    chapters = (
        review_files(settings, expand(settings, [chapters_dir]), index)
        if chapters_dir.is_dir()
        else []
    )
    chapters_by_path = {review.path: review for review in chapters}
    sections = []
    for r in ranked:
        section_facts = _facts_level(facts, r.reports, today)
        sections.append(
            SectionRow(
                ranked=r,
                decks=tuple(section_decks.get(r.section, ())),
                state=_section_state(r.files),
                findings=_findings_level(settings, by_report, r.reports),
                dated_facts=section_facts,
                opens=_section_opens(
                    settings, r, chapters_by_path, by_report, section_facts
                ),
            )
        )
    every_file = {
        review.path: review
        for review in [
            *(f for r in ranked for f in r.files),
            *(f for review in reviews for f in review.others),
            *chapters,
        ]
    }
    section_states = Counter(row.state for row in sections)
    file_states = Counter(f.state for r in ranked for f in r.files)
    totals = Totals(
        sections={
            state: section_states[state]
            for state in ("fresh", "due", "partial", "stale", "none")
        },
        files={
            state: file_states[state]
            for state in ("fresh", "due", "stale", "unreviewed", "deleted")
        },
        findings=_findings_totals(settings, by_report),
        course_notes=coverage.files,
        complete_decks=sum(coverage_share(d.entries) == 1 for d in coverage.decks),
        rules=tuple(
            RuleTotal(rule, count)
            for rule, count in _rules_due(settings, every_file.values())
        ),
        dated_facts_due=tuple(f.report for f in facts.values() if f.due(today)),
    )
    return Dashboard(
        today=today,
        totals=totals,
        sections=tuple(sections),
        decks=shown,
        left_out=left_out,
        sessions=sessions,
        problems=tuple(problems),
    )
