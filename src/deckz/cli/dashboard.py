from pathlib import Path
from typing import TYPE_CHECKING

from . import app
from ._groups import MAINTENANCE

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ..course_notes import ChapterEntry
    from ..dashboard import (
        Dashboard,
        DeckRow,
        FactsLevel,
        FilesLevel,
        FindingsLevel,
        Opens,
        SectionRow,
    )
    from ..sessions import CalendarEngagement

_TOP_SECTIONS = 15


@app.command(group=MAINTENANCE)
def dashboard(
    *,
    json: bool = False,
    all: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    sections: bool = False,
    refresh: bool = False,
    events: Path | None = None,
    workdir: Path = Path(),
) -> None:
    """Show what needs care: reviews, findings, course notes, next sessions.

    The totals, then each deck at five levels, each on its own: its content
    files are fresh (reviewed at their version), its labs are fresh (the
    notebooks its covering reports record), its deck pass holds, no covering
    section report has dated facts due, and no covering report has an open
    finding (`review.findings.critical`'s rubrics counted apart); then its
    course notes coverage and its chapters due under a rule (`review.rules`).
    Decks come by next session, then by frames to review. An INTRA deck (whose
    `deck.yml` has a `calendar` key) with no upcoming session is left out, as is
    one claiming a start over 31 days old when the calendar can't be read. Then
    the sections needing care with the highest score (`deckz review status`'s).

    The sessions come from `deckz sessions`' cache, never logging in: without
    the calendar, everything else is shown. Nothing is written.

    Args:
        json: Print one JSON object instead (every section, see the docs'
            "Maintenance dashboard" for its keys, kept stable for studioz)
        all: Show the past INTRA decks too
        sections: List every section, not only the first needing care
        refresh: Read Google Calendar now, even if the cache is recent
        events: Read the calendar's events from this JSON file instead
        workdir: Path to move into before running the command
    """
    from ..configuring.settings import GlobalSettings
    from ..dashboard import dashboard as build

    settings = GlobalSettings.from_yaml(workdir)
    found = build(settings, include_past=all, refresh=refresh, events_file=events)
    if json:
        from ._presentation import print_json

        print_json(dashboard_json(found))
    else:
        _print(found, every_section=sections)


########################################################################################
# JSON                                                                                 #
########################################################################################


def _files_json(level: "FilesLevel") -> dict[str, object]:
    return {
        "ok": level.ok,
        "total": len(level.files),
        "to_review": level.to_review,
        "counts": level.counts,
    }


def _findings_json(level: "FindingsLevel | None") -> dict[str, object] | None:
    if level is None:
        return None
    return {
        "ok": level.ok,
        "open": level.open,
        "total": level.total,
        "critical": level.critical,
        "reports": level.reports,
    }


def _facts_json(level: "FactsLevel") -> dict[str, object]:
    return {
        "ok": level.ok,
        "due": level.due,
        "reports": [
            {
                "report": f.report,
                "checked": f.checked,
                "source": f.source,
                "due_on": f.due_on,
            }
            for f in level.facts
        ],
    }


def _deck_facts_json(level: "FactsLevel") -> dict[str, object]:
    # A deck's covering reports are many: each shows in its section's row.
    due_on = [f.due_on for f in level.facts if f.due_on is not None]
    return {
        "ok": level.ok,
        "due": level.due,
        "next_due_on": min(due_on, default=None),
    }


def _counts(entries: "tuple[ChapterEntry, ...] | list[ChapterEntry]") -> dict:
    from ..course_notes import ChapterStatus

    found = {status.value: 0 for status in ChapterStatus}
    for entry in entries:
        found[entry.status.value] += 1
    return found


def _session_json(engagement: "CalendarEngagement | None") -> dict | None:
    # No place nor extra: the dashboard never names a client.
    if engagement is None:
        return None
    return {
        "start": engagement.start,
        "end": engagement.end,
        "days": engagement.days,
        "tentative": engagement.tentative,
        "intra": engagement.intra,
    }


def _opens_json(opens: "Opens | None") -> dict[str, str] | None:
    return None if opens is None else {"file": opens.file, "why": opens.why}


def _deck_json(row: "DeckRow") -> dict[str, object]:
    from ..course_notes import coverage_share

    notes = row.course_notes
    deck_pass = row.deck_pass
    return {
        "deck": row.deck,
        "intra": row.intra,
        "past": row.past,
        "next_session": _session_json(row.next_session),
        "sessions": None if row.sessions is None else len(row.sessions),
        "frames": row.frames,
        "levels": {
            "content": _files_json(row.content),
            "labs": _files_json(row.labs),
            "pass": {
                "ok": deck_pass.holds,
                "state": _pass_state(row),
                "report": deck_pass.report,
                "date": deck_pass.date,
                "stale": [f.path for f in deck_pass.files if f.state != "fresh"],
            },
            "dated_facts": _deck_facts_json(row.dated_facts),
            "findings": _findings_json(row.findings),
        },
        "course_notes": None
        if notes is None
        else {
            "counts": _counts(notes.entries),
            "share": coverage_share(notes.entries),
            "error": notes.error,
        },
        "chapters_due": [
            {"rule": rule.paths, "why": rule.why, "count": count}
            for rule, count in row.chapters_due
        ],
        "opens": _opens_json(row.opens),
    }


def _section_json(row: "SectionRow") -> dict[str, object]:
    ranked = row.ranked
    return {
        "section": row.section,
        "state": row.state,
        "score": ranked.score,
        "frames": ranked.frames,
        "decks": row.decks,
        "counts": {
            state: ranked.count(state)
            for state in ("fresh", "due", "stale", "unreviewed", "deleted")
        },
        "reports": ranked.reports,
        "findings": _findings_json(row.findings),
        "dated_facts": _facts_json(row.dated_facts),
        "needs_care": row.needs_care,
        "opens": _opens_json(row.opens),
    }


def dashboard_json(found: "Dashboard") -> dict[str, object]:
    """The dashboard as JSON-ready data, `deckz dashboard --json`.

    Returns:
        `{today, sessions, totals, decks, left_out, sections, problems}`.
    """
    from ..course_notes import coverage_share

    totals = found.totals
    findings = totals.findings
    sessions = found.sessions
    return {
        "today": found.today,
        "sessions": {
            "available": sessions.available,
            "why": sessions.why,
            "fetched_at": sessions.fetched_at,
            "note": sessions.note,
            "unmatched": sessions.unmatched,
            "problems": sessions.problems,
        },
        "totals": {
            "sections": totals.sections,
            "files": totals.files,
            "findings": None
            if findings is None
            else {
                "open": findings.open,
                "critical": findings.critical,
                "done": findings.done,
                "refused": findings.refused,
                "none": findings.none,
                "reports_with_open": findings.reports_with_open,
            },
            "course_notes": {
                "counts": _counts(list(totals.course_notes)),
                "share": coverage_share(totals.course_notes),
                "complete_decks": totals.complete_decks,
            },
            "rules": [
                {
                    "rule": r.rule.paths,
                    "since": r.rule.since,
                    "why": r.rule.why,
                    "due": r.due,
                }
                for r in totals.rules
            ],
            "dated_facts_due": totals.dated_facts_due,
        },
        "decks": [_deck_json(row) for row in found.decks],
        "left_out": found.left_out,
        "sections": [_section_json(row) for row in found.sections],
        "problems": found.problems,
    }


########################################################################################
# Human output                                                                         #
########################################################################################


def _pass_state(row: "DeckRow") -> str:
    if row.deck_pass.date is None:
        return "none"
    return "holds" if row.deck_pass.holds else "stale"


def _files_cell(level: "FilesLevel") -> str:
    if level.ok is None:
        return "—"
    return "✓" if level.ok else str(level.to_review)


def _facts_cell(level: "FactsLevel") -> str:
    if level.ok is None:
        return "—"
    return "✓" if level.ok else str(len(level.due))


def _findings_cell(level: "FindingsLevel | None") -> str:
    if level is None or level.ok is None:
        return "—"
    return f"{level.total} ({level.critical})" if level.critical else str(level.total)


def _notes_cell(row: "DeckRow") -> str:
    from ..course_notes import coverage_share

    share = (
        None if row.course_notes is None else coverage_share(row.course_notes.entries)
    )
    return "—" if share is None else f"{share:.0%}"


def _session_cell(engagement: "CalendarEngagement | None") -> str:
    if engagement is None:
        return "—"
    return f"{engagement.start}{'?' if engagement.tentative else ''}"


def _states[K: str](counts: "Mapping[K, int]", order: "Sequence[K]") -> str:
    return ", ".join(f"{counts[state]} {state}" for state in order if counts.get(state))


def _print_totals(found: "Dashboard") -> None:
    from ..course_notes import ChapterStatus, coverage_share

    totals = found.totals
    sections = totals.sections
    print(
        f"Sections  {sum(sections.values())} used by a deck: "
        f"{_states(sections, ('fresh', 'due', 'partial', 'stale'))}, "
        f"{sections['none']} with no report"
    )
    files = totals.files
    print(
        f"Files     {sum(files.values())}: "
        f"{_states(files, ('fresh', 'due', 'stale', 'unreviewed', 'deleted'))}"
    )
    if (findings := totals.findings) is not None:
        rubrics = ", ".join(f"{k} {n}" for k, n in findings.open.items())
        print(
            f"Findings  {sum(findings.open.values())} open in "
            f"{findings.reports_with_open} reports ({rubrics}); "
            f"{findings.done} done, {findings.refused} refused"
            + (f", {findings.none} with no outcome" if findings.none else "")
        )
    entries = totals.course_notes
    needed = sum(e.status is not ChapterStatus.SKIPPED for e in entries)
    have = sum(
        e.status in (ChapterStatus.WRITTEN, ChapterStatus.COVERED) for e in entries
    )
    share = coverage_share(entries)
    print(
        f"Notes     {have} of {needed} files needing a chapter have one"
        + ("" if share is None else f" ({share:.0%})")
        + f"; {totals.complete_decks} decks complete"
    )
    for rule in totals.rules:
        print(f"Due       {rule.due} files reviewed before {rule.rule.paths}'s rule")
    due = totals.dated_facts_due
    print(
        "Facts     "
        + (f"{len(due)} section reports' dated facts due" if due else "none due")
    )


def _print_decks(found: "Dashboard") -> None:
    with_sessions = found.sessions.available
    width = max((len(row.deck) for row in found.decks), default=4)
    head = f"{'next':<12}  " if with_sessions else ""
    print(
        f"\n{head}{'deck':<{width}}  content  labs  pass   facts     open  notes  due"
    )
    for row in found.decks:
        next_cell = f"{_session_cell(row.next_session):<12}  " if with_sessions else ""
        pass_cell = {"holds": "✓", "stale": "stale", "none": "—"}[_pass_state(row)]
        due = sum(count for _, count in row.chapters_due)
        print(
            f"{next_cell}{row.deck:<{width}}  {_files_cell(row.content):>7}  "
            f"{_files_cell(row.labs):>4}  {pass_cell:<5}  "
            f"{_facts_cell(row.dated_facts):>5}  {_findings_cell(row.findings):>7}  "
            f"{_notes_cell(row):>5}  {due or '':>3}"
        )
    print(
        "content, labs: files to review (✓ all fresh); pass: the deck pass; facts: "
        "reports with dated facts due;\nopen: open findings (critical ones in "
        "brackets); notes: files with a chapter; due: chapters due under a rule; "
        "—: nothing recorded"
    )


def _print_sections(found: "Dashboard", *, every: bool) -> None:
    rows = found.sections if every else [r for r in found.sections if r.needs_care]
    shown = rows if every else rows[:_TOP_SECTIONS]
    if not shown:
        return
    width = max(len(row.section) for row in shown)
    print(f"\n{'score':>6}  {'section':<{width}}  decks  state       open  facts")
    for row in shown:
        print(
            f"{row.ranked.score:>6}  {row.section:<{width}}  {len(row.decks):>5}  "
            f"{row.state:<7}  {_findings_cell(row.findings):>7}  "
            f"{_facts_cell(row.dated_facts):>5}"
        )
    if len(rows) > len(shown):
        print(
            f"({len(rows) - len(shown)} more needing care: deckz dashboard "
            "--sections, or deckz review status)"
        )


def _print(found: "Dashboard", *, every_section: bool) -> None:
    from sys import stderr

    _print_totals(found)
    _print_decks(found)
    _print_sections(found, every=every_section)
    sessions = found.sessions
    if not sessions.available:
        print(f"no sessions: {sessions.why}", file=stderr)
    else:
        read = (
            "from the events file"
            if sessions.fetched_at is None
            else f"read on {sessions.fetched_at.astimezone():%Y-%m-%d %H:%M}"
        )
        unmatched = (
            f", {sessions.unmatched} unmatched (deckz sessions)"
            if sessions.unmatched or sessions.problems
            else ""
        )
        print(f"calendar {read}{unmatched}", file=stderr)
        if sessions.note:
            print(sessions.note, file=stderr)
    if found.left_out:
        print(
            f"{len(found.left_out)} past INTRA decks left out (--all shows them)",
            file=stderr,
        )
    for problem in found.problems:
        print(problem, file=stderr)
