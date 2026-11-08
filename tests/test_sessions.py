import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pygit2 import init_repository
from pytest import CaptureFixture, fixture, raises

from deckz.cli import main
from deckz.configuring.settings import GlobalSettings, SessionsSettings
from deckz.exceptions import CalendarError, CalendarUnavailableError
from deckz.sessions import (
    Calendar,
    CalendarEngagement,
    RepositoryDecks,
    match_sessions,
    read_calendar,
    sessions_report,
)

_TITLE_PATTERN = r"""
  \s*
  (?P<tentative> \? \s+ )?
  (?P<continuation> -> \s+ )?
  (?P<company> .*? ) \s+ - \s+
  (?P<training> .*? ) \s+ - \s+
  (?P<place> .*? )
  (?: \s+ - \s+ (?P<extra> .*? ) )?
  \s*
"""

_DECKZ_YML = """\
sessions:
  companies:
    Acme: decks/acme
    beta: decks/beta-formation
    gamma: null
  trainings:
    acme/old: decks/acme/new-2026
    acme/gone: null
  catalog_intras:
    - {company: acme, training: abc, start: 2026-05-04}
  since: 2026-01-01
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")


def _deck(repo: Path, deck: str, extra: str = "") -> None:
    _write(
        repo / deck / "deck.yml", f"name: {deck.rsplit('/', 1)[-1]}\nparts: []\n{extra}"
    )


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repository(str(repo))
    _write(repo / "deckz.yml", _DECKZ_YML)
    _deck(repo, "decks/acme/abc")
    _deck(repo, "decks/acme/new-2026")
    _deck(repo, "decks/beta-formation/XYZ")
    _deck(
        repo,
        "decks/acme/INTRA/2026-03-client",
        "calendar: {training: ABC, start: 2026-03-02}\n",
    )
    user_dir = tmp_path / "user-config"
    _write(
        user_dir / "calendar.yml",
        json.dumps(
            {"calendar_id": "someone@example.com", "title_pattern": _TITLE_PATTERN}
        ),
    )
    monkeypatch.setattr("appdirs.user_config_dir", lambda *_, **__: str(user_dir))
    monkeypatch.chdir(repo)
    return repo


def _event(
    summary: str, start: str, days: int = 1, event_id: str | None = None
) -> dict[str, Any]:
    first = date.fromisoformat(start)
    return {
        "id": event_id or f"{summary}-{start}",
        "htmlLink": f"https://calendar.example/{start}",
        "summary": summary,
        "status": "confirmed",
        "start": {"date": str(first)},
        "end": {"date": str(first + timedelta(days=days))},
    }


_EVENTS = [
    _event("Acme - ABC - CV", "2025-06-02"),  # before since: ignored
    _event("Acme - ABC - CV", "2026-02-02", 3),
    _event("Acme - ABC - Paris - Intra Client", "2026-03-02", 2),  # claimed
    _event("-> Acme - ABC - Paris - Intra Client", "2026-03-09"),
    _event("ACME - abc - Lyon - Intra Other", "2026-05-04"),  # catalog_intras
    _event("Acme - ABC - Lille - Intra Third", "2026-06-01"),  # unclaimed INTRA
    _event("? Acme - OLD - CV", "2026-12-07", 2),  # tentative, trainings
    _event("Acme - GONE - CV", "2026-04-01"),  # null training: ignored
    _event("Acme - NODECK - CV", "2026-04-06"),  # no such deck
    _event("Beta - xyz - CV - with extra", "2026-11-16"),  # extra, not an INTRA
    _event("Gamma - ANY - CV", "2026-04-13"),  # null company: ignored
    _event("Delta - ANY - CV", "2026-04-20"),  # unknown company
]


def _events_file(tmp_path: Path, events: list[dict[str, Any]]) -> Path:
    path = tmp_path / "events.json"
    path.write_text(json.dumps(events), encoding="utf8")
    return path


def _report(repo: Path, tmp_path: Path, events: list[dict[str, Any]] = _EVENTS) -> Any:
    return sessions_report(
        GlobalSettings.from_yaml(repo),
        events_file=_events_file(tmp_path, events),
        today=date(2026, 11, 8),
    )


def test_each_engagement_goes_to_its_deck(repo: Path, tmp_path: Path) -> None:
    report = _report(repo, tmp_path)

    decks = {str(d.deck): [str(e.start) for e in d.engagements] for d in report.decks}
    assert decks == {
        # Upcoming first, by next session, then past ones, latest first.
        "decks/beta-formation/XYZ": ["2026-11-16"],
        "decks/acme/new-2026": ["2026-12-07"],
        "decks/acme/abc": ["2026-02-02", "2026-05-04"],
        "decks/acme/INTRA/2026-03-client": ["2026-03-02"],
    }
    assert list(decks)[:2] == ["decks/beta-formation/XYZ", "decks/acme/new-2026"]
    intra = report.decks[3].engagements[0]
    # The continuation is part of the claimed engagement.
    assert (intra.end, intra.days, intra.intra) == (date(2026, 3, 9), 3, True)
    tentative = report.decks[1].engagements[0]
    assert tentative.tentative
    assert report.ignored == 3


def test_orphans_say_their_fix(repo: Path, tmp_path: Path) -> None:
    report = _report(repo, tmp_path)

    orphans = {str(o.engagement.start): o for o in report.orphans}
    assert set(orphans) == {"2026-06-01", "2026-04-06", "2026-04-20"}
    intra = orphans["2026-06-01"]
    assert "INTRA" in intra.why
    assert "`calendar: {training: ABC, start: 2026-06-01}`" in intra.fix
    assert "{company: acme, training: abc, start: 2026-06-01}" in intra.fix
    assert "Third" not in intra.fix
    assert "no deck directory decks/acme/nodeck" in orphans["2026-04-06"].why
    assert "`acme/nodeck: <its deck directory>`" in orphans["2026-04-06"].fix
    assert "`delta: <its catalog directory>`" in orphans["2026-04-20"].fix
    assert report.problems == ()


def test_a_claim_or_entry_matching_no_engagement_is_a_problem(
    repo: Path, tmp_path: Path
) -> None:
    moved = [e for e in _EVENTS if "Intra Client" not in e["summary"]]
    moved.append(_event("Acme - ABC - Paris - Intra Client", "2026-03-16"))
    moved = [e for e in moved if "Intra Other" not in e["summary"]]

    report = _report(repo, tmp_path, moved)

    assert report.problems == (
        "decks/acme/INTRA/2026-03-client/deck.yml: its calendar key names no abc "
        "engagement starting 2026-03-02 (the calendar has one starting "
        "2026-02-02, 2026-03-16): fix its start",
        "sessions.catalog_intras in deckz.yml: no acme/abc engagement starts on "
        "2026-05-04 (the calendar has one starting 2026-03-16, 2026-06-01): fix "
        "its start, or remove the entry",
    )


def test_claims_outside_a_catalog_and_twice_are_problems(
    repo: Path, tmp_path: Path
) -> None:
    _deck(repo, "elsewhere/deck", "calendar: {training: ABC, start: 2026-03-02}\n")
    _deck(
        repo, "decks/acme/INTRA/copy", "calendar: {training: abc, start: 2026-03-02}\n"
    )
    _write(repo / "decks/acme/broken/deck.yml", "name: [\n")

    problems = _report(repo, tmp_path).problems

    assert any("decks/acme/broken/deck.yml doesn't read" in p for p in problems)
    assert any(
        "elsewhere/deck/deck.yml has a calendar key, but no catalog" in p
        for p in problems
    )
    assert any(
        "decks/acme/INTRA/2026-03-client/deck.yml and decks/acme/INTRA/copy/deck.yml"
        " both claim" in p
        for p in problems
    )


def test_settings_reject_unknown_companies_and_case_duplicates() -> None:
    with raises(ValidationError, match="other/abc must start with a company"):
        SessionsSettings.model_validate(
            {"companies": {"acme": "decks/acme"}, "trainings": {"other/abc": None}}
        )
    with raises(ValidationError, match="must start with a company"):
        SessionsSettings.model_validate(
            {"companies": {"acme": "decks/acme"}, "trainings": {"abc": None}}
        )
    with raises(ValidationError, match="'acme' and 'ACME' are the same key"):
        SessionsSettings.model_validate(
            {"companies": {"acme": "decks/acme", "ACME": "decks/acme"}}
        )


def test_match_sessions_without_settings_makes_every_session_an_orphan() -> None:
    engagement = CalendarEngagement(
        event_id="e",
        link="",
        company="Acme",
        training="ABC",
        place="CV",
        extra=None,
        start=date(2026, 1, 5),
        end=date(2026, 1, 5),
        days=1,
        tentative=False,
        intra=False,
    )
    report = match_sessions(
        SessionsSettings(),
        Calendar((engagement,)),
        RepositoryDecks({}, {}, ()),
        date.today(),
    )

    assert [o.engagement for o in report.orphans] == [engagement]


def _fetching(monkeypatch: Any, events: list[Any] | Exception) -> list[bool]:
    calls: list[bool] = []

    def fetch(calendar_id: str, *, login: bool) -> list[Any]:
        assert calendar_id == "someone@example.com"
        calls.append(login)
        if isinstance(events, Exception):
            raise events
        return events

    monkeypatch.setattr("deckz.extras.calendar.fetch_events", fetch)
    return calls


def test_events_are_cached_for_cache_hours(
    repo: Path, tmp_path: Path, monkeypatch: Any
) -> None:
    settings = GlobalSettings.from_yaml(repo)
    cache = tmp_path / "cache"
    now = datetime(2026, 11, 8, 9, tzinfo=UTC)
    calls = _fetching(monkeypatch, [_event("Acme - ABC - CV", "2026-02-02")])

    first = read_calendar(settings, cache_dir=cache, now=now)
    again = read_calendar(settings, cache_dir=cache, now=now + timedelta(hours=23))

    assert calls == [False]
    assert first == again
    assert first.fetched_at == now
    (cached,) = cache.iterdir()
    assert cached.stat().st_mode & 0o777 == 0o600
    assert cache.stat().st_mode & 0o777 == 0o700

    read_calendar(settings, cache_dir=cache, now=now + timedelta(hours=25))
    read_calendar(settings, cache_dir=cache, now=now, refresh=True, login=True)

    assert calls == [False, False, True]


def test_a_failed_fetch_falls_back_on_the_cache(
    repo: Path, tmp_path: Path, monkeypatch: Any
) -> None:
    settings = GlobalSettings.from_yaml(repo)
    cache = tmp_path / "cache"
    now = datetime(2026, 11, 8, 9, tzinfo=UTC)
    _fetching(monkeypatch, [_event("Acme - ABC - CV", "2026-02-02")])
    read_calendar(settings, cache_dir=cache, now=now)
    _fetching(monkeypatch, CalendarError("reading Google Calendar failed: offline"))

    stale = read_calendar(settings, cache_dir=cache, now=now, refresh=True)

    assert len(stale.engagements) == 1
    assert stale.note is not None
    assert "rereading failed: reading Google Calendar failed: offline" in stale.note

    with raises(CalendarError, match="offline"):
        read_calendar(settings, cache_dir=tmp_path / "empty", now=now)


def test_without_a_login_reading_fails_with_the_fix(repo: Path, tmp_path: Path) -> None:
    # The tests' XDG_CONFIG_HOME holds no schedz token.
    with raises(CalendarUnavailableError, match="deckz sessions --login"):
        read_calendar(GlobalSettings.from_yaml(repo), cache_dir=tmp_path / "cache")


def test_without_calendar_settings_reading_fails_with_the_fix(
    repo: Path, tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr("appdirs.user_config_dir", lambda *_, **__: str(tmp_path / "x"))

    with raises(CalendarUnavailableError, match=r"calendar\.yml.*calendar_id"):
        read_calendar(GlobalSettings.from_yaml(repo))


def test_invalid_calendar_settings_name_the_file(
    repo: Path, tmp_path: Path, monkeypatch: Any
) -> None:
    user_dir = tmp_path / "bad"
    _write(user_dir / "calendar.yml", "title_pattern: '(?P<company>.*)'\n")
    monkeypatch.setattr("appdirs.user_config_dir", lambda *_, **__: str(user_dir))

    with raises(CalendarError, match=r"calendar\.yml is invalid"):
        read_calendar(GlobalSettings.from_yaml(repo))


def test_without_schedz_reading_fails_with_the_install_command(
    repo: Path, monkeypatch: Any
) -> None:
    monkeypatch.delitem(sys.modules, "deckz.extras.calendar", raising=False)
    monkeypatch.delattr("deckz.extras.calendar", raising=False)
    monkeypatch.setitem(sys.modules, "schedz", None)
    monkeypatch.setitem(sys.modules, "schedz.exceptions", None)

    with raises(CalendarUnavailableError, match=r'"deckz\[calendar\]"'):
        read_calendar(GlobalSettings.from_yaml(repo))


def test_cli_prints_the_sessions(
    repo: Path, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    events = _events_file(tmp_path, _EVENTS)

    main(("sessions", "--json", "--events", str(events)))

    found = json.loads(capsys.readouterr().out)
    decks = {d["deck"]: d["sessions"] for d in found["decks"]}
    assert decks["decks/acme/new-2026"][0]["tentative"] is True
    assert {o["session"]["start"] for o in found["orphans"]} == {
        "2026-06-01",
        "2026-04-06",
        "2026-04-20",
    }
    assert found["ignored"] == 3
    assert found["fetched_at"] is None

    main(("sessions", "--events", str(events)))

    captured = capsys.readouterr()
    assert "decks/acme/new-2026\n" in captured.out
    assert "(tentative)" in captured.out
    assert "3 sessions no deck matches:" in captured.out
    assert "calendar from the events file" in captured.err
