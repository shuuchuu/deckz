"""The user's calendar, through schedz: the only module importing it.

Needs the calendar extra (`pip install "deckz[calendar]"`); `deckz.sessions`
imports this module lazily, so deckz works without it.
"""

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Self

from pydantic import Field, ValidationError, model_validator
from schedz.exceptions import SchedzError
from schedz.grouping import Engagement
from schedz.loading import fetch_calendar, read_engagements, read_events_file
from schedz.settings import CalendarSettings
from yaml import YAMLError, safe_load

from ..exceptions import CalendarError, CalendarUnavailableError

INSTALL_HINT = 'pip install "deckz[calendar]"'
SETTINGS_FILENAME = "calendar.yml"


class UserCalendarSettings(CalendarSettings, extra="forbid", frozen=True):
    """The user's `calendar.yml`: schedz's settings, plus deckz's own.

    schedz's are `calendar_id`, `title_pattern` (a verbose regex with the groups
    `continuation`, `company`, `training`, `place`, and optionally `extra` and
    `tentative`) and `durations`, as invoicez reads them.
    """

    calendars: dict[str, str] = Field(default_factory=dict)
    """Several calendars read together, by a short label (e.g. a colleague's
    name) shown with each of their sessions: the calendar ids, instead of
    `calendar_id`. Each is read on its own, so a continuation only continues a
    session of its own calendar."""

    intra_pattern: str = r"(?i)^intra\b"
    """A regex searched in a title's extra part: a match makes the session an
    INTRA, which belongs to the deck claiming it, not to its catalog deck."""
    cache_hours: float = Field(default=24, gt=0)
    """How long the events read from Google Calendar serve before deckz reads
    them again (`deckz sessions --refresh` rereads them at once)."""

    @model_validator(mode="after")
    def _check_intra_pattern(self) -> Self:
        try:
            re.compile(self.intra_pattern)
        except re.error as e:
            msg = f"intra_pattern does not compile: {e}"
            raise ValueError(msg) from e
        return self

    @model_validator(mode="after")
    def _check_calendars(self) -> Self:
        if self.calendar_id is not None and self.calendars:
            msg = (
                "calendar_id and calendars are both set: list every calendar in "
                "calendars, yours included, and remove calendar_id"
            )
            raise ValueError(msg)
        if len(set(self.calendars.values())) < len(self.calendars):
            msg = "calendars names one calendar id twice"
            raise ValueError(msg)
        return self

    def sources(self) -> dict[str | None, str]:
        """The calendars to read, by label (None: `calendar_id`, unlabelled).

        Returns:
            Label to calendar id; empty when neither key is set.
        """
        if self.calendar_id is not None:
            return {None: self.calendar_id}
        sources: dict[str | None, str] = {}
        sources.update(self.calendars)
        return sources


def load_settings(user_config_dir: Path) -> UserCalendarSettings:
    """Read the user's `calendar.yml`.

    Returns:
        The settings.

    Raises:
        CalendarUnavailableError: If the file is missing.
        CalendarError: If it is invalid.
    """
    path = user_config_dir / SETTINGS_FILENAME
    if not path.is_file():
        msg = (
            f"no calendar settings: write {path} with your calendar's "
            "`calendar_id` (or several, `calendars`) and `title_pattern` "
            "(invoicez's `gcal` settings have both), as deckz's guide (Sessions) "
            "shows"
        )
        raise CalendarUnavailableError(msg)
    try:
        return UserCalendarSettings.model_validate(
            safe_load(path.read_text(encoding="utf8")) or {}
        )
    except (ValidationError, YAMLError) as e:
        msg = f"{path} is invalid:\n{e}"
        raise CalendarError(msg) from e


def logged_in() -> bool:
    """Whether schedz has a token: reading the calendar won't open a browser.

    Returns:
        True when the token file exists (it may still need a refresh).

    Raises:
        CalendarUnavailableError: If the Google libraries are missing.
    """
    from schedz.loading import google_api

    try:
        google = google_api(INSTALL_HINT)
    except SchedzError as e:
        raise CalendarUnavailableError(str(e)) from e
    return google.token_path().is_file()


def fetch_events(calendar_id: str, *, login: bool) -> list[dict[str, Any]]:
    """Read every event of the calendar from Google Calendar.

    Args:
        calendar_id: The calendar to read.
        login: Log in (in a browser) when schedz has no token yet, instead of
            failing.

    Returns:
        The raw events.

    Raises:
        CalendarUnavailableError: If the Google libraries are missing, or no
            token is cached and `login` is false.
        CalendarError: If reading the calendar fails.
    """
    if not login and not logged_in():
        msg = (
            "not logged in to Google Calendar: run `deckz sessions --login` once "
            "(it opens a browser; the token is shared with invoicez)"
        )
        raise CalendarUnavailableError(msg)
    try:
        return fetch_calendar(calendar_id, INSTALL_HINT)
    except SchedzError as e:
        raise CalendarUnavailableError(str(e)) from e
    # The network, OAuth and the Google API each raise their own exceptions:
    # all of them mean the calendar couldn't be read this time.
    except Exception as e:
        msg = f"reading Google Calendar failed: {e}"
        raise CalendarError(msg) from e


def read_file(path: Path) -> list[dict[str, Any]]:
    """Read raw events from a JSON file, e.g. an anonymised fixture.

    Returns:
        The raw events.

    Raises:
        CalendarError: If the file doesn't hold a JSON list.
    """
    try:
        return read_events_file(path)
    except (SchedzError, OSError, ValueError) as e:
        msg = f"can't read events from {path}: {e}"
        raise CalendarError(msg) from e


def engagements(
    raw_events: Iterable[Mapping[str, Any]], settings: UserCalendarSettings
) -> tuple[list[Engagement], list[str]]:
    """Read the events as engagements: a session and its continuations.

    Returns:
        The engagements, by start date, and the messages of the events that
        match the title pattern but can't be read (schedz's errors; its
        warnings are about billing, invoicez's business).
    """
    found, diagnostics = read_engagements(raw_events, settings)
    return found, [d.message for d in diagnostics if d.level == "error"]
