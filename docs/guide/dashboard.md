# Maintenance dashboard

`deckz dashboard` tells what of the repository needs care, and in which deck first:
what was reviewed and what changed since, the findings left open, the course notes
written, the chapters due under a rule added later, and the next session of each
deck. It reads what the other commands measure ([Reviews](reviews.md),
[Sessions](sessions.md), `deckz show course-notes`) and writes nothing.

```sh
deckz dashboard             # the totals, the decks, the sections needing care
deckz dashboard --all       # the past INTRA decks too
deckz dashboard --sections  # every section, not only the 15 first needing care
deckz dashboard --json      # everything, for a script or studioz
```

It takes about as long as `deckz review status` and `deckz show course-notes` together
(15 s for 40 decks): every deck is parsed.

## The totals

- **Sections**: the shared sections some deck uses, by state: *fresh* (every file at
  the version reviewed), *due* (fresh, but reviewed before a rule), *partial* (a file
  never reviewed), *stale* (a file changed since its review), and *with no report*.
- **Files**: their files, by state.
- **Findings**: the open findings of every report, by rubric, and how many are done or
  refused (with `review.findings`).
- **Notes**: the share of the content files needing a course notes chapter that have
  one, and the decks where all do.
- **Due**: per rule of `review.rules`, the files reviewed before it.
- **Facts**: the section reports whose dated facts are due (with
  `review.dated_facts`).

## The decks

Each deck is up to date at five levels, shown each on its own:

| Column | Met (✓) when | Otherwise |
|---|---|---|
| content | every content file of the deck is fresh | how many aren't |
| labs | every notebook (or other file) the reports covering the deck record is fresh | how many aren't |
| pass | its deck pass holds (see [Deck reports](reviews.md#deck-reports)) | `stale`: its own files changed; `—`: none recorded |
| facts | no section report covering it has dated facts due | how many have |
| open | no report covering it has an open finding | how many are open, the `critical` rubrics' in brackets |

The reports covering a deck are those `deckz review findings <deck>` reads: its own,
and those recording one of its content files or course notes chapters. `—` means
nothing to judge: no report records a notebook, or none covers the deck. Then come
`notes`, its course notes coverage, and `due`, its chapters due under a rule.

The decks with an upcoming session come first, the next one first (`?` marks a
tentative booking), then the others by frames to review: every frame of their content
files never reviewed, and those the changes of their stale files touch (as `deckz
review status` scores sections).

An INTRA deck, one whose `deck.yml` claims a calendar session (`calendar`), is left out
once that session is past: when the calendar shows no upcoming session for it, or,
when the calendar can't be read, when its claimed start is more than 31 days ago.
`--all` shows them.

## The sessions

They come from `deckz sessions`' cache, read again when it's older than `cache_hours`
(`--refresh`: now). The dashboard never logs in: without the calendar extra, your
settings or a login, it says why in one line and shows everything else, with no
`next` column. A session shows its dates and days only, never its place or the rest
of its title, so the dashboard's output never names a client; when `calendar.yml`
lists several `calendars`, it also shows the label of the session's calendar.

## The JSON

`--json` prints one object. studioz reads it: its keys are kept stable.

- `today`; `sessions`: `{available, why, fetched_at, note, unmatched, problems}`.
- `totals`: `sections` and `files` (counts by state, every state), `findings` (null
  without `review.findings`: `{open: {<rubric>: n}, critical, done, refused, none,
  reports_with_open}`), `course_notes` (`{counts, share, complete_decks}`), `rules`
  (`[{rule, since, why, due}]`), `dated_facts_due` (reports).
- `decks`, in the order shown: `{deck, intra, past, next_session, sessions, frames,
  levels, course_notes, chapters_due, opens}`. `next_session` is `{start, end, days,
  tentative, intra, calendar}` or null (`calendar`: its calendar's label, null with
  `calendar_id`); `sessions` the number of its sessions, null without the
  calendar. `levels` has `content` and `labs` (`{ok, total, to_review, counts}`),
  `pass` (`{ok, state, report, date, stale}`), `dated_facts` (`{ok, due,
  next_due_on}`) and `findings` (`{ok, open, total, critical, reports}`, null without
  `review.findings`); each `ok` is true, false, or null when there is nothing to judge.
  `course_notes` is `{counts, share, error}`, `chapters_due` `[{rule, why, count}]`,
  `opens` the file to open about it (below).
- `left_out`: the past INTRA decks not shown.
- `sections`, every one, by score: `{section, state, score, frames, decks, counts,
  reports, findings, dated_facts, needs_care, opens}`, `dated_facts` being `{ok, due,
  reports: [{report, checked, source, due_on}]}`, `needs_care` whether it's among
  those the human output lists (not fresh, an open finding, or dated facts due).
- `problems`: the reports that couldn't be read, the findings breaking the grammar.
- `opens`, on a deck and a section: `{file, why}`, a file of the repository that
  exists, or null. studioz's Maintenance page opens it in its editor when a row is
  clicked. A deck opens its first chapter due under a rule (`why`: `chapter_due`),
  else its deck report (`report`); null: its deck page. A section opens the first of
  its files' chapters due under a rule (`chapter_due`), else the chapter of its first
  file not fresh (`chapter`), else that file's report, or its section's (`report`),
  else that file itself (`file`); a section needing care only for its findings or
  dated facts opens the report holding them.
