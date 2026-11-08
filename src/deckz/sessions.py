"""Which deck each training session of the user's calendar teaches.

The sessions come from the user's Google Calendar through schedz
(`deckz.extras.calendar`, imported lazily: without the calendar extra, its
settings or a login, `read_calendar` raises `CalendarUnavailableError` and
everything else works). `match_sessions` then gives each engagement its deck from
`deckz.yml`'s `sessions` and the decks' own `calendar` keys, and reports the
sessions no deck matches with the fix. Nothing it reads from the repository names a
client; the calendar's titles do, and stay in the user's cache.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path, PurePosixPath
from re import compile as compile_regex
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from yaml import YAMLError, safe_load

from .configuring.settings import GlobalSettings, SessionsSettings
from .exceptions import CalendarError, CalendarUnavailableError
from .models import CalendarClaim, DeckDefinition
from .utils import all_deck_settings

if TYPE_CHECKING:
    from .extras.calendar import UserCalendarSettings

# A claim or an entry matching no engagement names the engagements of its
# training this close to its date, likely the session it meant.
_NEAR = timedelta(days=62)


@dataclass(frozen=True)
class CalendarEngagement:
    """A session of the calendar and its continuations, as deckz reads them."""

    event_id: str
    """The Google event id of its root session."""
    link: str
    """The root event's page in Google Calendar."""
    company: str
    training: str
    place: str
    extra: str | None
    """The title's extra part, e.g. an INTRA's client: never written to the \
    repository."""
    start: date
    end: date
    """Inclusive."""
    days: float
    """Days taught, a half-day counting half."""
    tentative: bool
    """Unconfirmed: one of its sessions is (the title pattern's `tentative`)."""
    intra: bool
    """Its extra part matches the user's `intra_pattern`."""

    @property
    def key(self) -> tuple[str, str, date]:
        """What a claim matches: company and training (casing ignored), start."""
        return self.company.casefold(), self.training.casefold(), self.start


@dataclass(frozen=True)
class Calendar:
    """The engagements read from the calendar, and how they were read."""

    engagements: tuple[CalendarEngagement, ...]
    errors: tuple[str, ...] = ()
    """Events matching the title pattern that couldn't be read."""
    fetched_at: datetime | None = None
    """When Google Calendar was read (None: from an events file)."""
    note: str | None = None
    """Why older events than `cache_hours` allows were used, if they were."""


@dataclass(frozen=True)
class DeckSessions:
    deck: PurePosixPath
    """The deck's directory, relative to the git root."""
    engagements: tuple[CalendarEngagement, ...]
    """By start date."""


@dataclass(frozen=True)
class Orphan:
    """An engagement no deck matches, and the edit that gives it one."""

    engagement: CalendarEngagement
    why: str
    fix: str


@dataclass(frozen=True)
class SessionsReport:
    decks: tuple[DeckSessions, ...]
    """Decks with a session: the next upcoming one first, then those with \
    past sessions only, the latest first."""
    orphans: tuple[Orphan, ...]
    problems: tuple[str, ...]
    """Claims and entries matching no engagement, unreadable `deck.yml` \
    files: each says its fix."""
    ignored: int
    """Engagements ending before `sessions.since`, or of a company or \
    training mapped to null."""
    calendar: Calendar = field(default_factory=lambda: Calendar(()))


def _cache_path(cache_dir: Path, calendar_id: str) -> Path:
    # One file per calendar: changing calendar_id doesn't reuse another's.
    digest = sha256(calendar_id.encode("utf8")).hexdigest()[:16]
    return cache_dir / f"{digest}.json"


def _read_cache(path: Path) -> tuple[datetime, list[dict[str, Any]]] | None:
    try:
        data = json.loads(path.read_text(encoding="utf8"))
        return datetime.fromisoformat(data["fetched_at"]), data["events"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cache(path: Path, fetched_at: datetime, events: list[Any]) -> None:
    # The events name clients: readable by the user only, and written whole
    # (a temporary file renamed) so a reader never sees half of them.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    temporary.touch(mode=0o600)
    temporary.write_text(
        json.dumps({"fetched_at": fetched_at.isoformat(), "events": events}),
        encoding="utf8",
    )
    temporary.replace(path)


def default_cache_dir() -> Path:
    """Where the calendar's events are cached: the user's cache directory.

    Returns:
        `~/.cache/deckz/calendar` on Linux. It may not exist.
    """
    import appdirs

    from . import app_name

    return Path(appdirs.user_cache_dir(app_name)) / "calendar"


def _calendar_module() -> Any:
    try:
        from .extras import calendar
    except ModuleNotFoundError as e:
        if (e.name or "").partition(".")[0] not in {"schedz", "google"}:
            raise
        msg = 'reading the calendar needs schedz: pip install "deckz[calendar]"'
        raise CalendarUnavailableError(msg) from e
    return calendar


def _raw_events(
    user: "UserCalendarSettings",
    cache_dir: Path,
    *,
    refresh: bool,
    login: bool,
    now: datetime,
) -> tuple[list[dict[str, Any]], datetime, str | None]:
    calendar = _calendar_module()
    if user.calendar_id is None:
        msg = (
            "calendar_id isn't set in calendar.yml: copy invoicez's "
            "(`invoicez gcal calendars` lists your calendars)"
        )
        raise CalendarUnavailableError(msg)
    path = _cache_path(cache_dir, user.calendar_id)
    cached = _read_cache(path)
    if (
        cached is not None
        and not refresh
        and now - cached[0] < timedelta(hours=user.cache_hours)
    ):
        return cached[1], cached[0], None
    try:
        events = calendar.fetch_events(user.calendar_id, login=login)
    except CalendarError as e:
        if cached is None:
            raise
        note = f"events read on {cached[0]:%Y-%m-%d %H:%M}, rereading failed: {e}"
        return cached[1], cached[0], note
    _write_cache(path, now, events)
    return events, now, None


def read_calendar(
    settings: GlobalSettings,
    *,
    refresh: bool = False,
    login: bool = False,
    events_file: Path | None = None,
    cache_dir: Path | None = None,
    now: datetime | None = None,
) -> Calendar:
    """Read the engagements of the user's calendar, from the cache when recent.

    Google Calendar is read again once the cache is older than `cache_hours`
    (the user's `calendar.yml`); when that fails, the cache serves, with a
    note saying so.

    Args:
        settings: The settings: their user config directory holds
            `calendar.yml`.
        refresh: Read Google Calendar now, whatever the cache's age.
        login: Log in (in a browser) when schedz has no token yet.
        events_file: Read the raw events from this JSON file instead (e.g.
            an anonymised fixture): no cache, no Google.
        cache_dir: Where the events are cached (default: `default_cache_dir`).
        now: The current time (default: now).

    It raises `CalendarUnavailableError` when the calendar extra,
    `calendar.yml`, its `calendar_id` or a login is missing (and no cache
    serves), `CalendarError` when `calendar.yml` is invalid.

    Returns:
        The engagements, by start date.
    """
    calendar = _calendar_module()
    user = calendar.load_settings(settings.paths.user_config_dir)
    fetched_at: datetime | None = None
    note = None
    if events_file is not None:
        raw = calendar.read_file(events_file)
    else:
        raw, fetched_at, note = _raw_events(
            user,
            default_cache_dir() if cache_dir is None else cache_dir,
            refresh=refresh,
            login=login,
            now=datetime.now(UTC) if now is None else now,
        )
    found, errors = calendar.engagements(raw, user)
    intra = compile_regex(user.intra_pattern)
    return Calendar(
        engagements=tuple(
            CalendarEngagement(
                event_id=e.id,
                link=e.root.html_link,
                company=e.company,
                training=e.training,
                place=e.place,
                extra=e.extra,
                start=e.start,
                end=e.end,
                days=sum(
                    s.quantity * (1 if s.kind == "day" else 0.5) for s in e.sessions
                ),
                tentative=e.tentative,
                intra=e.extra is not None and intra.search(e.extra) is not None,
            )
            for e in found
        ),
        errors=tuple(errors),
        fetched_at=fetched_at,
        note=note,
    )


@dataclass(frozen=True)
class RepositoryDecks:
    """Every deck directory, by its path casefolded, and their claims."""

    by_folded: Mapping[str, PurePosixPath]
    claims: Mapping[PurePosixPath, CalendarClaim]
    problems: tuple[str, ...]


def read_decks(settings: GlobalSettings) -> RepositoryDecks:
    """Find every deck of the repository and its `calendar` key.

    Returns:
        The decks and their claims; a `deck.yml` that doesn't read is a
        problem, not an error.
    """
    git_dir = settings.paths.git_dir
    decks: dict[str, PurePosixPath] = {}
    claims: dict[PurePosixPath, CalendarClaim] = {}
    problems: list[str] = []
    for deck_settings in all_deck_settings(git_dir):
        path = deck_settings.paths.deck_definition
        deck = PurePosixPath(path.parent.relative_to(git_dir).as_posix())
        decks[deck.as_posix().casefold()] = deck
        try:
            definition = DeckDefinition.model_validate(
                safe_load(path.read_text(encoding="utf8"))
            )
        except (ValidationError, YAMLError) as e:
            problems.append(f"{deck}/deck.yml doesn't read: {e}")
            continue
        if definition.calendar is not None:
            claims[deck] = definition.calendar
    return RepositoryDecks(by_folded=decks, claims=claims, problems=tuple(problems))


def _folded(mapping: Mapping[str, str | None]) -> dict[str, str | None]:
    return {key.casefold(): value for key, value in mapping.items()}


def _catalog_of(deck: PurePosixPath, catalogs: Mapping[str, str | None]) -> str | None:
    # The company whose catalog holds the deck, the deepest catalog winning.
    holding = [
        (len(PurePosixPath(catalog).parts), company)
        for company, catalog in catalogs.items()
        if catalog is not None
        and deck.as_posix()
        .casefold()
        .startswith(PurePosixPath(catalog).as_posix().casefold() + "/")
    ]
    return max(holding)[1] if holding else None


def _near(
    engagements: Iterable[CalendarEngagement], company: str, training: str, day: date
) -> str:
    near = sorted(
        str(e.start)
        for e in engagements
        if e.company.casefold() == company
        and e.training.casefold() == training
        and abs(e.start - day) <= _NEAR
    )
    return f" (the calendar has one starting {', '.join(near)})" if near else ""


def match_sessions(
    sessions: SessionsSettings,
    calendar: Calendar,
    decks: RepositoryDecks,
    today: date,
) -> SessionsReport:
    """Give each engagement its deck, and say which ones get none and why.

    A deck whose `calendar` key names an engagement gets it. Otherwise an
    INTRA engagement goes to its catalog deck only when
    `sessions.catalog_intras` lists it, and any other to the catalog deck its
    training code names (`sessions.trainings` first, then the directory of
    that name, casing ignored).

    Args:
        sessions: The repository's `sessions` settings.
        calendar: The engagements.
        decks: The repository's decks and their claims (`read_decks`).
        today: Today, for which sessions are upcoming.

    Returns:
        The decks' sessions, the orphans, and the problems.
    """
    companies = _folded(sessions.companies)
    trainings = _folded(sessions.trainings)
    problems = list(decks.problems)
    claims: dict[tuple[str, str, date], PurePosixPath] = {}
    for deck, claim in decks.claims.items():
        company = _catalog_of(deck, companies)
        if company is None:
            problems.append(
                f"{deck}/deck.yml has a calendar key, but no catalog of "
                "sessions.companies in deckz.yml holds it: add its catalog there"
            )
            continue
        key = (company, claim.training.casefold(), claim.start)
        if (other := claims.setdefault(key, deck)) != deck:
            problems.append(
                f"{other}/deck.yml and {deck}/deck.yml both claim the {claim.training} "
                f"engagement starting {claim.start}: keep the key in one of them"
            )
    intras = {
        (i.company.casefold(), i.training.casefold(), i.start)
        for i in sessions.catalog_intras
    }
    kept = [
        e
        for e in calendar.engagements
        if sessions.since is None or e.end >= sessions.since
    ]
    ignored = len(calendar.engagements) - len(kept)
    by_deck: dict[PurePosixPath, list[CalendarEngagement]] = {}
    orphans: list[Orphan] = []
    for engagement in kept:
        found = _deck_of(engagement, companies, trainings, claims, intras, decks)
        if found is None:
            ignored += 1
        elif isinstance(found, Orphan):
            orphans.append(found)
        else:
            by_deck.setdefault(found, []).append(engagement)
    problems.extend(_unmatched(sessions, claims, intras, kept))
    return SessionsReport(
        decks=_sorted_decks(by_deck, today),
        orphans=tuple(orphans),
        problems=tuple(problems),
        ignored=ignored,
        calendar=calendar,
    )


def _deck_of(
    engagement: CalendarEngagement,
    companies: Mapping[str, str | None],
    trainings: Mapping[str, str | None],
    claims: Mapping[tuple[str, str, date], PurePosixPath],
    intras: set[tuple[str, str, date]],
    decks: RepositoryDecks,
) -> PurePosixPath | Orphan | None:
    # The engagement's deck, its orphan, or None when it's ignored.
    if (claimed := claims.get(engagement.key)) is not None:
        return claimed
    company, training = engagement.company.casefold(), engagement.training.casefold()
    if company not in companies:
        return Orphan(
            engagement,
            f"the company {engagement.company!r} isn't in sessions.companies",
            f"add `{company}: <its catalog directory>` to sessions.companies in "
            "deckz.yml (`null` if its sessions use no deck of this repository)",
        )
    catalog = companies[company]
    if catalog is None:
        return None
    code = f"{company}/{training}"
    if code in trainings:
        target = trainings[code]
        if target is None:
            return None
        named_by = f"sessions.trainings names {target}"
    else:
        target = f"{PurePosixPath(catalog).as_posix()}/{training}"
        named_by = f"no deck directory {target}"
    if engagement.intra and engagement.key not in intras:
        return Orphan(
            engagement,
            "an INTRA session no deck claims (its program may differ from the "
            "catalog's)",
            f"add `calendar: {{training: {engagement.training}, start: "
            f"{engagement.start}}}` to the deck.yml of the deck made for it; or, "
            f"if {target} is taught as is, `{{company: {company}, training: "
            f"{training}, start: {engagement.start}}}` to sessions.catalog_intras "
            "in deckz.yml",
        )
    deck = decks.by_folded.get(target.casefold())
    if deck is None:
        return Orphan(
            engagement,
            f"{named_by}, which holds no deck.yml",
            f"add `{code}: <its deck directory>` to sessions.trainings in deckz.yml "
            "(`null` if taught without a deck of this repository)",
        )
    return deck


def _unmatched(
    sessions: SessionsSettings,
    claims: Mapping[tuple[str, str, date], PurePosixPath],
    intras: set[tuple[str, str, date]],
    engagements: Sequence[CalendarEngagement],
) -> list[str]:
    # The claims and catalog_intras entries no engagement matches: each one
    # was meant for a session, likely moved since.
    keys = {e.key for e in engagements}

    def counts(day: date) -> bool:
        return sessions.since is None or day >= sessions.since

    problems = [
        f"{deck}/deck.yml: its calendar key names no {training} engagement starting "
        f"{day}{_near(engagements, company, training, day)}: fix its start"
        for (company, training, day), deck in claims.items()
        if (company, training, day) not in keys and counts(day)
    ]
    problems.extend(
        f"sessions.catalog_intras in deckz.yml: no {company}/{training} engagement "
        f"starts on {day}{_near(engagements, company, training, day)}: fix its "
        "start, or remove the entry"
        for company, training, day in sorted(intras)
        if (company, training, day) not in keys and counts(day)
    )
    return problems


def _sorted_decks(
    by_deck: Mapping[PurePosixPath, list[CalendarEngagement]], today: date
) -> tuple[DeckSessions, ...]:
    def order(item: tuple[PurePosixPath, list[CalendarEngagement]]) -> tuple:
        deck, found = item
        upcoming = [e.start for e in found if e.end >= today]
        if upcoming:
            return (0, min(upcoming).toordinal(), str(deck))
        return (1, -max(e.end for e in found).toordinal(), str(deck))

    return tuple(
        DeckSessions(deck, tuple(sorted(found, key=lambda e: e.start)))
        for deck, found in sorted(by_deck.items(), key=order)
    )


def sessions_report(
    settings: GlobalSettings,
    *,
    refresh: bool = False,
    login: bool = False,
    events_file: Path | None = None,
    today: date | None = None,
) -> SessionsReport:
    """Read the calendar and give each of its engagements its deck.

    It raises what `read_calendar` raises.

    Returns:
        The report (`match_sessions`).
    """
    calendar = read_calendar(
        settings, refresh=refresh, login=login, events_file=events_file
    )
    return match_sessions(
        settings.sessions,
        calendar,
        read_decks(settings),
        date.today() if today is None else today,
    )
