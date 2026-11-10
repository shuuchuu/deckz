from pathlib import Path
from typing import TYPE_CHECKING

from . import app

if TYPE_CHECKING:
    from datetime import date

    from ...analyzing.dated_facts import DatedFacts


@app.command(name="dated-facts")
def dated_facts(
    targets: list[Path] | None = None,
    /,
    *,
    due: bool = False,
    on: str | None = None,
    calendar: bool = False,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Print the lists of dated facts of section reports, and when each is due.

    A section report lists its dated facts under `review.dated_facts.heading`,
    after its findings: one table row per fact (its file, its frame, the
    fact in full, the day or month its source states it as of, the source),
    which a check of the facts reads instead of the content files. Each
    report is due in a month of its own, no later than its last check (its
    `review.dated_facts.line`, else the day it was added) plus its section's
    delay: the reports of one delay are spread over the months, at most
    `ceil(n / delay)` of their `n` a month, a check brought forward rather
    than late. For each report: its due month, its last check, its deadline,
    then its rows; a report without a list says so (its next check writes
    it). The `review-dated-facts` check fails on the reports due,
    `review-facts-list` on a malformed list.

    Always exits 0: it only informs.

    Args:
        targets: Shared sections (`content/genai`, or `genai`), each standing
            for its report and those of its subsections, or section reports
            and directories under `review.dir`'s `sections/`; none for every
            section report
        due: Only the reports due on ON
        on: The day the facts are judged due on, `YYYY-MM-DD`, or a month,
            `YYYY-MM`, for its last day (what's due by the end of it); today
            by default
        calendar: Print how many reports fall due each month instead, by
            delay: the spreading at a glance
        json: Print one JSON object instead: `{on, reports: [{report,
            section, checked, source, months, deadline, due_on, due, listed,
            facts: [{line, file, frame, fact, date, source}]}], calendar:
            {YYYY-MM: {<months>: count}}}`, `checked`, `deadline` and
            `due_on` null for a report not committed yet
        workdir: Path to move into before running the command

    """
    from ...analyzing.dated_facts import due_by_month, targeted
    from ...configuring.settings import GlobalSettings

    settings = GlobalSettings.from_yaml(workdir)
    day = _day(on)
    found = targeted(settings, targets or [])
    shown = [f for f in found if f.due(day)] if due else found
    if json:
        from .._presentation import print_json

        print_json(
            {
                "on": day.isoformat(),
                "reports": [_json(f, day) for f in shown],
                "calendar": due_by_month(shown),
            }
        )
        return
    if calendar:
        _print_calendar(shown)
        return
    grammar = settings.review.dated_facts
    heading = grammar.heading if grammar is not None else None
    for facts in shown:
        _print_report(facts, day, heading)
    listed = [f for f in shown if f.listed]
    print(
        f"{len(shown)} reports{' due' if due else ''}, "
        f"{sum(f.due(day) for f in shown)} due on {day}; {len(listed)} with a "
        f"list ({sum(len(f.facts) for f in listed)} facts)"
    )
    if heading is None:
        print(
            "No list is read: set `review.dated_facts.heading` in deckz.yml (e.g. "
            "`heading: Dated facts`)."
        )


def _day(on: str | None) -> "date":
    from calendar import monthrange
    from datetime import date

    from ...exceptions import DeckzError

    if on is None:
        return date.today()
    try:
        if len(on) == 7:
            year, month = (int(part) for part in on.split("-"))
            return date(year, month, monthrange(year, month)[1])
        return date.fromisoformat(on)
    except ValueError as error:
        msg = f"--on {on}: give a day, YYYY-MM-DD, or a month, YYYY-MM"
        raise DeckzError(msg) from error


def _json(facts: "DatedFacts", day: "date") -> dict[str, object]:
    def iso(value: "date | None") -> str | None:
        return None if value is None else value.isoformat()

    return {
        "report": facts.report,
        "section": facts.section,
        "checked": iso(facts.checked),
        "source": facts.source,
        "months": facts.months,
        "deadline": iso(facts.deadline),
        "due_on": iso(facts.due_on),
        "due": facts.due(day),
        "listed": facts.listed,
        "facts": [
            {
                "line": f.line,
                "file": f.file,
                "frame": f.frame,
                "fact": f.fact,
                "date": f.date,
                "source": f.source,
            }
            for f in facts.facts
        ],
    }


def _print_report(facts: "DatedFacts", day: "date", heading: str | None) -> None:
    if facts.due_on is None:
        when = "not committed yet, no date"
    else:
        since = "checked" if facts.source == "line" else "report added"
        due = "DUE since" if facts.due(day) else "due"
        when = (
            f"{due} {facts.due_on:%Y-%m}; {since} {facts.checked}, every "
            f"{facts.months} months (by {facts.deadline})"
        )
    if facts.listed:
        listing = f"{len(facts.facts)} facts"
    else:
        listing = "no list yet" + (f" (« {heading} »)" if heading else "")
    print(f"{facts.report}: {when}; {listing}")
    for fact in facts.facts:
        print(
            f"  l.{fact.line:<4} {fact.file} | {fact.frame} | {fact.fact} | "
            f"{fact.date} | {fact.source}"
        )


def _print_calendar(shown: "list[DatedFacts]") -> None:
    from ...analyzing.dated_facts import due_by_month

    counts = due_by_month(shown)
    delays = sorted({m for by_delay in counts.values() for m in by_delay})
    print("month    " + "".join(f"{f'{m} months':>11}" for m in delays) + "  total")
    for month, by_delay in counts.items():
        cells = "".join(f"{by_delay.get(m, 0):>11}" for m in delays)
        print(f"{month}  {cells}  {sum(by_delay.values()):>5}")
