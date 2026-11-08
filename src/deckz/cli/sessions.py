from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from . import app
from ._groups import MAINTENANCE

if TYPE_CHECKING:
    from ..sessions import CalendarEngagement, SessionsReport


@app.command(group=MAINTENANCE)
def sessions(
    *,
    json: bool = False,
    refresh: bool = False,
    login: bool = False,
    events: Path | None = None,
    workdir: Path = Path(),
) -> None:
    """Show each deck's past and upcoming sessions, from your Google Calendar.

    Each engagement of the calendar (a session and its continuations) goes to
    the deck whose `deck.yml` claims it (`calendar: {training, start}`), else to
    its catalog's deck (`sessions` in `deckz.yml`: the company's catalog, the
    training code's deck directory). An INTRA session goes to its catalog's deck
    only when `sessions.catalog_intras` says it is taught as is. The sessions no
    deck matches are listed with the edit that fixes them, and so are the
    claims matching no session. Tentative sessions are marked, and so is each
    session's calendar when `calendars` lists several (e.g. a colleague's).

    Needs the calendar extra (`pip install "deckz[calendar]"`), your
    `~/.config/deckz/calendar.yml` (calendar ids, title pattern) and a login
    (`--login`, once, shared with invoicez). The events are cached in your cache
    directory for `cache_hours` (24 by default).

    Args:
        json: Print one JSON object instead: `{decks: [{deck, sessions}],
            orphans: [{session, why, fix}], problems, ignored, calendar_errors,
            fetched_at, note}`, a session being `{event_id, link, company,
            training, place, extra, start, end, days, tentative, intra,
            calendar, upcoming}`, `calendar` being the label of its calendar in
            `calendars` (null with `calendar_id`)
        refresh: Read Google Calendar now, even if the cache is recent
        login: Log in to Google Calendar if needed (opens a browser)
        events: Read the events from this JSON file instead of Google Calendar
            (e.g. an anonymised fixture)
        workdir: Path to move into before running the command
    """
    from ..configuring.settings import GlobalSettings
    from ..sessions import sessions_report

    settings = GlobalSettings.from_yaml(workdir)
    report = sessions_report(settings, refresh=refresh, login=login, events_file=events)
    today = date.today()
    if json:
        _print_json(report, today)
    else:
        _print(report, today)


def _line(engagement: "CalendarEngagement", today: date) -> str:
    when = "upcoming" if engagement.end >= today else "past"
    days = f"{engagement.days:g} d"
    place = engagement.place + (f" - {engagement.extra}" if engagement.extra else "")
    tentative = "  (tentative)" if engagement.tentative else ""
    calendar = f"  — {engagement.calendar}" if engagement.calendar else ""
    return (
        f"  {when:<8}  {engagement.start} → {engagement.end}  {days:>5}  "
        f"{engagement.training}  {place}{tentative}{calendar}"
    )


def _print(report: "SessionsReport", today: date) -> None:
    from sys import stderr

    for deck in report.decks:
        print(deck.deck)
        for engagement in deck.engagements:
            print(_line(engagement, today))
    if report.orphans:
        print(f"\n{len(report.orphans)} sessions no deck matches:")
        for orphan in report.orphans:
            engagement = orphan.engagement
            print(f"{_line(engagement, today)}  [{engagement.company}]")
            print(f"    {orphan.why}: {orphan.fix}")
    if report.problems:
        print(f"\n{len(report.problems)} problems:")
        for problem in report.problems:
            print(f"  {problem}")
    if report.calendar.errors:
        print(f"\n{len(report.calendar.errors)} calendar events that don't read:")
        for error in report.calendar.errors:
            print(f"  {error}")
    calendar = report.calendar
    read = (
        "from the events file"
        if calendar.fetched_at is None
        else f"read on {calendar.fetched_at.astimezone():%Y-%m-%d %H:%M}"
    )
    print(
        f"{sum(len(d.engagements) for d in report.decks)} sessions in "
        f"{len(report.decks)} decks, {len(report.orphans)} unmatched, "
        f"{report.ignored} ignored; calendar {read}",
        file=stderr,
    )
    if calendar.note:
        print(calendar.note, file=stderr)


def _engagement_json(engagement: "CalendarEngagement", today: date) -> dict:
    return {
        "event_id": engagement.event_id,
        "link": engagement.link,
        "company": engagement.company,
        "training": engagement.training,
        "place": engagement.place,
        "extra": engagement.extra,
        "start": engagement.start,
        "end": engagement.end,
        "days": engagement.days,
        "tentative": engagement.tentative,
        "intra": engagement.intra,
        "calendar": engagement.calendar,
        "upcoming": engagement.end >= today,
    }


def _print_json(report: "SessionsReport", today: date) -> None:
    from ._presentation import print_json

    calendar = report.calendar
    print_json(
        {
            "decks": [
                {
                    "deck": deck.deck,
                    "sessions": [_engagement_json(e, today) for e in deck.engagements],
                }
                for deck in report.decks
            ],
            "orphans": [
                {
                    "session": _engagement_json(o.engagement, today),
                    "why": o.why,
                    "fix": o.fix,
                }
                for o in report.orphans
            ],
            "problems": report.problems,
            "ignored": report.ignored,
            "calendar_errors": calendar.errors,
            "fetched_at": calendar.fetched_at,
            "note": calendar.note,
        }
    )
