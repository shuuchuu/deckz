# Sessions

`deckz sessions` tells which deck each of your training sessions teaches, past and
upcoming, from your Google Calendar. It's how you see what to prepare next, and the
sessions no deck matches yet.

It reads the calendar through [schedz](https://github.com/shuuchuu/schedz), the
library invoicez bills from: one login serves both.

## Setting it up

1. Install the extra: `pip install "deckz[calendar]"` (in a repository managed
   with uv, add `calendar` to deckz's extras in its `pyproject.toml`).
2. Write your calendar settings in `~/.config/deckz/calendar.yml`. They are yours,
   not the repository's: no `deckz.yml` key can set them.

   ```yaml
   calendar_id: someone@example.com
   # Verbose regex: groups continuation, company, training, place, and
   # optionally extra and tentative. Titles are matched whole.
   title_pattern: |
     \s*
     (?P<tentative> \? \s+ )?
     (?P<continuation> -> \s+ )?
     (?P<company> .*? ) \s+ - \s+
     (?P<training> .*? ) \s+ - \s+
     (?P<place> .*? )
     (?: \s+ - \s+ (?P<extra> .*? ) )?
     \s*
   # Optional: a regex searched in the extra part, which makes a session an
   # INTRA (default below), and how long the events serve before deckz reads
   # them again (hours, default 24).
   intra_pattern: (?i)^intra\b
   cache_hours: 24
   ```

   If you use invoicez, copy `calendar_id` and `title_pattern` from its
   `settings.yml` (`gcal`).

   To follow a colleague's sessions too (e.g. you review the decks they teach),
   share their calendar with your Google account, then list every calendar under
   `calendars` instead of `calendar_id`, each with a short label of your choice:

   ```yaml
   calendars:
     Me: someone@example.com
     Alex: alex@example.com
   ```

   Their titles must follow the same `title_pattern`. Each calendar is read and
   cached on its own: a continuation (`->`) only continues a session of its own
   calendar. invoicez keeps reading `calendar_id` from its own settings, so it bills
   your sessions only.
3. Log in once: `deckz sessions --login` opens a browser for Google's consent. The
   token lands in `~/.config/schedz/`, next to the OAuth client secrets that
   schedz's README says how to create. If invoicez already logged in before it read
   its calendar through schedz, any `invoicez gcal` command moves its files there.

Without the extra, the settings or the login, `deckz sessions` says which is
missing, and everything else in deckz works as before.

## How a session finds its deck

A session's title names a company and a training code, e.g. `Orsys - PYT - CV`.
The repository's `deckz.yml` maps them to decks (see the README, `sessions`):

- `companies` gives each company's catalog directory (`orsys: decks/orsys`). The
  training code names the catalog's deck directory of that name, casing ignored:
  `PYT` is `decks/orsys/pyt`.
- `trainings` lists the codes whose deck has another name
  (`orsys/dpl: decks/orsys/dpl-2026`), or `null` for a training taught without a
  deck of this repository.
- Sessions ending before `since` are ignored.

An **INTRA** session (its extra part matches `intra_pattern`, e.g. `Orsys - DRN -
Paris - Intra Acme`) is made for one client, and its program differs from the
catalog's, slightly or a lot. So it never goes to the catalog deck silently:

- the deck made for it claims it in its `deck.yml`, with
  `calendar: {training: DRN, start: 2026-01-12}` (the training code, and the first
  day of its first session);
- or, when the catalog deck is taught as is, `deckz.yml` says so:
  `sessions.catalog_intras: [{company: orsys, training: drn, start: 2026-01-12}]`.
  Without `start`, the entry covers every INTRA of that training, e.g. a client's
  recurring sessions (`{company: sparks, training: npy}`); a deck claiming one of
  them still gets it.

Neither names the client: the client's name stays in your calendar.

## Reading the output

```sh
deckz sessions            # every deck with a session, the next one first
deckz sessions --refresh  # read the calendar now, not from the cache
deckz sessions --json     # for a script
```

Each deck lists its sessions (`upcoming` or `past`, dates, days, code, place,
`(tentative)` for a booking marked `?`, and `— <label>` for its calendar's label
when `calendars` lists several). Then come:

- **sessions no deck matches**, each with the edit that gives it one: a company or
  a code to map, an INTRA to claim or to declare taught with the catalog deck;
- **problems**: a `calendar` key or a `catalog_intras` entry no session matches
  (the session moved: fix the date; deckz names the sessions of that training
  starting close to it), a key in a deck no catalog holds;
- the calendar's events that match the title pattern but can't be read.

The events are cached in your cache directory (`~/.cache/deckz/calendar/`, readable
by you only, one file per calendar) for `cache_hours`. When reading a calendar fails
(offline), its cache serves, with a note saying when it was read.
