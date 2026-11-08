# Maintenance dashboard: the state of a deckz repository, from deckz alone

Planned 2026-11-08 from a status report an agent computed by hand on
shuuchuu/slides (its measurement and the decisions taken are in slides'
`docs/plans/tableau-de-bord-maintenance.md`). The goal: one command, and a
studioz page, that tell the maintainer what needs care, without an agent.

## What the hand-made report needed, and what deckz lacks

| Measure | Source today | Gap |
| --- | --- | --- |
| Sections with a report, fresh, stale, unreviewed | `deckz review status --json` | totals and shares only |
| Content and labs reviewed per deck | `deckz review status <deck>` | one deck per call |
| Open findings per report, by rubric | none: the agent parsed report bodies (37 of ~2,600 unreadable) | a findings grammar, a parser, a check |
| Decks that had a deck pass, and whether it still holds | none: prose reports archived with plans, no header | deck reports in the registry |
| Course notes coverage | `deckz show course-notes --json`, per deck | a repository-wide mode, distinct files |
| Course notes chapters due for a rule added later (the hierarchy pass) | none: guessed from an `{.aside` box, the rule's commit date, the pass's commits | review of `supports/`, and rule dates |
| Dated facts due | slides' `qa-dated-facts` check (`tools/checks.py`) | generic, so the dashboard can read it |
| Next session of each deck | none (the maintainer's calendar) | calendar access, shared with invoicez |

Also: `deckz review status` and `review diff` only read, but `_DECKZ_READ_ONLY_PAIRS`
(`agent_checkouts.py`) lacks them, so an agent can't run them in the main checkout.

## Decisions (2026-11-08, the maintainer)

- Deck reports are living reports in the registry (slides: `docs/qa/decks/<deck>.md`),
  not plans.
- Sessions come from the maintainer's Google Calendar, through the code invoicez
  already has (`invoicez gcal`), extracted into a library both tools use: **schedz**,
  in its own repository (see phase 4).
- A deck is up to date at five levels, each shown on its own: its content is fresh,
  its labs are fresh, its deck pass is newer than its last change, no dated fact is
  due, and no finding of its sections is open (errors counted apart).

## Phases

### 0. Small fixes

- `review: {status, diff}` in `_DECKZ_READ_ONLY_PAIRS`, after checking that neither
  writes anything (cache included).
- `deckz show course-notes` with no `--workdir` inside a deck: every deck, plus the
  distinct content files with their status (`--json`).

**Done 2026-11-08** (`ace8f19`, `5b39bea`, not pushed): `status` and `diff` checked
read-only on slides (nothing written in the checkout, its git directory, objects or
refs); `course_notes.repository_coverage` behind `show course-notes` run outside a
deck, which reproduces the 2026-11-08 measurement on slides (925 files, 40 %).

### 1. Findings

A finding grammar owned by deckz, configured in `deckz.yml` (`review.findings`):
the heading that holds findings, the rubrics (letter, heading), the outcome words
(slides: *ouvert*, *fait*, *refusé*). One finding is one list item starting
`**<letter><n>**`; its outcome is the last outcome word of its first paragraph
(or a fixed trailing line: settle it on slides' 92 reports, where outcomes after a
blank line or after a sub-list are the unreadable cases). Verdicts that are not
findings (slides' *adaptée*) live outside the findings heading.

- `review-findings` check: a finding with no outcome, two items with one id, an
  unknown rubric; the message names the fix.
- `deckz review findings [TARGET] [--json]`: per report, counts by rubric and outcome;
  with a deck, the open findings of the reports covering its files.

**Done 2026-11-08** (branch `review-findings`, not pushed): `analyzing/findings.py`,
`FindingsSettings`, the `review-findings` check (blocking, a no-op without
`review.findings`), `deckz review findings` (allowed to agents in the main checkout).
Settled on slides' 92 reports: the outcome is the **last** emphasized outcome word of
the item, the item read as Markdown does (indented lines, blank lines, lazy
continuation). That reads 2,615 of 2,619 findings; the "37 unreadable" of the hand
measurement were its parser's (it stopped at a blank line), not the reports'. The 4
left have no outcome at all (`genai/assistant-config` I2, `nn/generative` C6 and C10,
and `genai` C14, whose text has C15 spliced into it). Open: 369 in 37 reports (126 P,
119 C, 90 I, 33 A, 1 E), 2,129 done, 117 refused. List items with no id (slides'
*adaptée* verdicts) aren't findings, so they need not move.

### 2. Deck reports

- The registry covers several kinds: `review.dir` becomes the parent (`docs/qa`), with
  kinds by subdirectory (`sections/`, `decks/`, `supports/`), or `review.dirs` with a
  kind each. Keep "a file several reports record takes the most recent mark".
- A deck report records `deck.yml`, `variables.yml`, `program.md` and the deck's
  `content/`. Its pass holds while those files are fresh: changes to its shared
  sections show at the content level, not here. Document it in `analyzing.md`.
- `deckz review mark --at <commit>`: record the blobs of a past commit, to register a
  pass made before (slides: orsys/pyt 2026-10-28, orsys/pya 2026-11-04,
  sparks-formation/bdm 2026-11-07). It keeps `changed_elsewhere`'s refusal relative to
  that commit.

**Prepared 2026-11-08, after phase 1 (nothing coded yet).** What the code does today,
and what to settle first.

- *One directory.* Everything goes through `review.review_dir(settings)` (the
  `review.dir` setting); `report_paths` is an `rglob("*.md")` under it, and
  `all_reports`, `marks_index` (most recent mark per file: by `date`, then by the
  `base` commit's time), `ranking`, `deck_review` and `findings.findings_status` read
  every report it finds. Setting `review.dir: docs/qa` would already pick up
  `docs/qa/sections/**` and `docs/qa/decks/**` with no new setting. The only thing
  that needs to know the kind is the dashboard. The kind could come from the
  subdirectory, or from the content: a report that records a `deck.yml` is that
  deck's report. Prefer the content rule (no setting) unless phase 3's `supports/`
  reports need their own rule; decide that here.
- *Ranking side effects.* A deck report recording `deck.yml`, `variables.yml` and
  `program.md` doesn't touch `ranking` (none of them is a content file). Recording the
  deck's own `content/` files makes it a covering report of that deck in `deck_review`
  (`others`) and in `review findings <deck>`, which is what we want.
- *Findings of a deck report.* The `review-findings` check and `review findings` read
  every report under `review.dir` with one grammar (`review.findings`). Slides'
  three deck reports (`docs/plans/archive/{pyt,pya,bdm}-qa-report.md`) don't follow
  it: their rubrics are `##` headings with no `## Constats` above them, and pyt and
  bdm number nothing (pya has 23 ids). Moved as they are, their findings would be
  invisible (not wrong: items outside the heading aren't findings). Two options:
  reformat the three into the sections' form (`## Constats`, `###` rubrics, ids,
  outcomes; one grammar; the recommended one, about 900 lines in all), or a grammar
  per kind. Their closing section "Constats des sections" (open section findings
  copied by hand) can then go: `deckz review findings <deck>` produces it.
- *`mark --at <commit>`.* `mark` writes through `_write_report(path, date, base,
  files)` with `base` = HEAD and the working-tree blobs (`blobs`, `git hash-object`).
  `--at` takes the blobs at the commit instead (`git rev-parse <commit>:<path>`, or
  one `git ls-tree -r`), `base` = the commit, `date` = its commit date. It records
  that commit's versions, so files changed since then show as stale, which is right.
  Then `changed_elsewhere` has nothing to refuse: check this, and say so in the
  docstring rather than keep a refusal with no purpose. A path missing at that commit
  is an error that names it.
- *Slides' passes to register:* orsys/pyt on `c6985bae` (2026-10-28, named in its
  report), orsys/pya on `589afdad`'s parent (2026-11-04, the commit that added the
  report), sparks-formation/bdm on `26eceac3`'s parent (2026-11-07). Confirm each from
  `git log` before marking.

**Done 2026-11-08** (branch `deck-reports`). Settled with the maintainer: one
findings grammar (slides reformats its three deck reports into the sections' form), and
a report's kind comes from its **path**, so that a script finds a report without reading
it: `<review.dir>/sections/**` a section's report, `<review.dir>/<deck directory>.md` a
deck's (the same path arithmetic as the Drive links registry), anything else a
`review-headers` failure (a deck renamed leaves its report misplaced: `git mv`). No new
setting: `review.dir` is the parent (`docs/qa`). `review.report_kind`,
`deck_report_path`, `deck_own_files` (tracked and unignored files under the deck's
directory, minus `en/` and nested decks); `mark` on a deck's report records them with no
path, takes the deck's directory for them, and refuses shared content;
`DeckReview.deck_pass` (`DeckPass`: the own files against the deck report's marks
alone, `holds`), shown by `review status <deck>` (human, `--plain` lines for the own
files not listed already, `--json` `deck_pass`); `review findings <deck>` includes the
deck's report. `mark --at <commit>` only on a report recording nothing yet (so
`changed_elsewhere` has nothing to refuse, said in the docstring), the commit in HEAD's
history, every file present at it; `base` = the commit, `date` = its `%cs`. Phase 3's
`supports/` reports get a third kind by path the same way.

### 3. Rule dates and dated facts

- `review.rules`: `[{paths: <glob>, since: <date>, why: <text>}]`. A file marked before
  `since` is *due* (a fourth state beside fresh/stale/unreviewed, shown with `why`).
  Slides' first one: `supports/**`, 2026-10-23, the hierarchy rules
  (`dff3788f`).
- `review.dated_facts`: the fast-moving sections and the two delays (slides: 6 and 12
  months), moving `qa-dated-facts` from slides' `tools/checks.py` into deckz (slides
  then drops its own and keeps the opt-in name).

**Done 2026-11-08** (branch `review-rules`). Settled with the maintainer: a file's
mark has its **own date** when it differs from its report's (`path: {blob, date,
base}` when its day or base differs; the plain `path: <sha>` form stays for the
others, so no existing report changes; written with no YAML alias): a report's single
date would let a pass on one chapter clear the rule for its siblings, and `mark --at`
couldn't register passes made at different commits in one report. So `mark` keeps the
day of the files it doesn't mark, and `--at` now refuses only files the report already
records, and finds a file renamed since the commit under its old path (`git diff -M`).
`review.rules` (`ReviewRule`: `paths`
glob with `full_match`, `since`, `why`; `since` a day, or a time compared with the
mark's base commit time, because slides' rule came at 16:15 on a day whose morning
wrote chapters before it): `due_rules`, a fifth state `due` (fresh but
marked before a rule; a stale file lists its rules too, `FileReview.due`), counted
whole in the frames to review, shown by `review status` (a column, `due` in `--json`,
the rule's `why` under the file, the fix: mark it again by name). Course notes
reports are a third kind by path, `<review.dir>/<course notes directory>/**`
(`course_notes_reports_dir`); a course notes directory given to `status`/`mark`
stands for its French chapters; `DeckReview.chapters` (a deck's written French
chapters) in `review status <deck>`. `review.dated_facts` (`line`, `months`,
`sections` by path, longest wins): `analyzing/dated_facts.py`, the
`review-dated-facts` check, opt-in in deckz itself (`OPT_IN`: its verdict changes as
days pass); the date is the latest such line, else the author date the report was
added under `sections/`, following renames there. Not done here: `deckz status`'s
review counts ignore `due` (`deck_counts`), left for the dashboard (phase 5).

### 4. Sessions from the calendar

- Extract from invoicez's `gcal/` the calendar layer: `google.py` (OAuth, read-only
  scopes, token cache), `parsing.py` (`Session`, title pattern, durations,
  tentative and continuation), `grouping.py` (`Engagement`), the `--events FILE`
  fixture loading and `anonymize.py`. invoicez keeps billing (`pricing`, `drafting`,
  `reconcile`, `linking`) and depends on schedz. schedz has its own config directory
  (`~/.config/schedz/`: OAuth client secrets, token), so one login serves both tools;
  invoicez's existing token and secrets move there once.
- schedz's repository, set up like invoicez's: generated from the shuuchuu
  `template` (Copier, `package` layout, tools `bumpver`, `doit`, `githooks`,
  `pytest`), pushed to GitHub (`shuuchuu/schedz`) as invoicez is, no CI: the QA runs
  in the pre-commit hooks (prek, `doit check` and the tests). Releases are uploaded
  to PyPI with `uv build` and `uv publish`, the PyPI token read from a gitignored
  `creds.env` (as invoicez's), through a `doit publish` task so nobody types it.
  Creating the GitHub repository, the PyPI project and the first upload are the
  maintainer's. invoicez's gcal tests (`tests/gcal/`, the anonymised
  `events.json` fixture) split along the same line.
- **Done 2026-11-08, not pushed:** schedz `7222153` (`diagnostics`, `settings` with
  `CalendarSettings`, `parsing`, `grouping`, `google`, `loading`: `read_events_file`,
  `fetch_calendar`, `read_engagements`, `google_api(install_hint)`); invoicez branch
  `schedz` `a7f046f` (in the worktree `../invoicez-schedz`): `GcalSettings` extends
  `CalendarSettings`, the OAuth files move once to `~/.config/schedz/`,
  `anonymize.py` and the fixture script stay in invoicez, and its tests no longer
  inherit a hook's `GIT_DIR`. schedz 0.1.0 pushed and on PyPI (2026-11-08); invoicez
  takes it from PyPI (`a7e0c83`, merged into its `main`, not pushed). Left: push
  and release invoicez (the maintainer's).
- deckz: an optional extra (`deckz[calendar]`, on schedz); `calendar` settings in the user's
  `~/.config/deckz/` (calendar id, title pattern), never in the repository; a mapping
  from (company, training) to a deck directory in `deckz.yml` (company key to catalog
  directory, training code to deck directory, casing ignored), and an optional
  `calendar` key in an INTRA deck's `deck.yml` for the session it was made for.
- Events are cached in `~/.cache/deckz/` (a TTL, `--refresh`). Client names never
  enter the repository: slides keeps business documents out (its `CLAUDE.md`).
- `deckz sessions [--json]`: past and upcoming sessions per deck, tentative ones
  marked, and the sessions no deck matches (with the fix: the mapping or the key).
- Without the extra or the credentials, everything else works, with no session
  column.
- **Settled 2026-11-08 (the maintainer):**
  - `deckz.yml`'s `sessions`: `companies` maps a calendar company key (casing
    ignored) to its catalog directory (or null: no deck here); a training code
    names the catalog's deck directory of that name (casing ignored), and
    `trainings` lists only the exceptions (`<company>/<code>: <deck dir>`, or null:
    taught without a deck here); sessions ending before `since` are ignored.
  - The user's settings are their own file, `~/.config/deckz/calendar.yml`
    (schedz's `CalendarSettings`, plus `intra_pattern`, a regex on the title's
    extra part, `(?i)^intra\b` by default), which no repository file can set.
  - An INTRA deck's `calendar: {training, start}` (the code and the first day of the
    engagement's root session) claims that engagement. An INTRA session no deck
    claims is an orphan, not a session of the catalog deck (an INTRA's program
    differs from the catalog's, slightly or a lot): the fix is an INTRA deck with
    that key, or a `sessions.catalog_intras` entry (`{company, training, start}`, no
    client name) saying the catalog deck is taught as is. A key or an entry
    matching no engagement is reported.
  - Revised on the real calendar (almost every session is an INTRA, many a
    client's recurring sessions of one training): a `catalog_intras` entry
    without `start` covers every INTRA of its training.
- **Done 2026-11-08** (`c5ec1a3` and its follow-up, branch `sessions`): `deckz
  sessions`, `extras.calendar`, `sessions`; slides' mapping in its step 4.

### 5. The command

`deckz dashboard [--json]`, a read-only aggregate of the above:

- totals: sections with a report (fresh, stale, partial, none), files, open findings
  by rubric, course notes coverage, chapters due by rule;
- per section: decks, state, open findings, dated facts due;
- per deck: the five levels, course notes coverage, chapters due, next session;
  sorted by next session, then by the review score `review status` already uses;
  past INTRA decks with no upcoming session left out unless `--all`.

**Settled 2026-11-08 (the maintainer), branch `dashboard`:**

- The five levels. *Content*: every content file of the deck fresh (due, stale,
  unreviewed or deleted is not). *Labs*: the files other than content the reports
  covering the deck record (`DeckReview.others`, the notebooks) all fresh: deckz
  knows a deck's notebooks no other way (the links are the repository's Jinja
  filter); a notebook no report records doesn't count, its section fails *content*
  anyway. *Pass*: `DeckPass.holds` (holds, stale, none). *Dated facts*: no covering
  section report has its facts due today. *Findings*: no open finding in the
  reports `review findings <deck>` shows (those recording a content file of the
  deck, and its own); the rubrics of a new `review.findings.critical` (slides: `[E]`)
  are counted apart. A level with nothing to judge (no notebook recorded, no
  covering report) is neither met nor failed (`null`).
- A section's state, first that applies: none (no file recorded), stale (a file
  stale or deleted), partial (a file unreviewed), due, fresh.
- Deck order: next session's start, then the deck's frames to review (all frames
  of its unreviewed content files, the changed ones of its stale files:
  `DeckReview.frames`), then path.
- An INTRA deck is one whose `deck.yml` has a `calendar` key. It is past, and left
  out unless `--all`, when the calendar shows no upcoming engagement for it, or,
  the calendar unreadable, when its claimed start is more than 31 days ago.
- Sessions from `sessions_report` with no login (`--refresh` passed on); on any
  `CalendarError`, no session column and the reason in one line. A session shows
  its start, end, days, tentative and intra only: no place nor extra, so the
  dashboard never names a client.
- Human output: the totals, the decks, then the 15 sections needing care with the
  highest score (`--sections` for all of them); `--json` has everything.
- Revised once built: a deck's covering reports also count those recording its
  written French chapters (`review.deck_covered_paths`), in `review findings <deck>`
  too (slides: sparks-formation/bdm's 5 open course notes findings, 1 E, were
  invisible to its deck).

**Done 2026-11-08** (branch `dashboard`): `deckz/dashboard.py` (tasks layer:
`Dashboard`, `DeckRow`, `SectionRow`, `FilesLevel`, `FindingsLevel`, `FactsLevel`,
`Totals`), `deckz dashboard [--json] [--all] [--sections] [--refresh] [--events]`
(`cli/dashboard.py`, allowed to agents in the main checkout),
`review.findings.critical`, `DeckReview.content`/`frames`, the guide's
"Maintenance dashboard" page (with the JSON keys, which `studioz.md` now lists as
kept stable), `tasks.md`. On slides (2026-11-08, 16 s): 154 sections (75 fresh,
43 stale, 36 with no report), 922 files (704 fresh, 71 stale, 147 unreviewed), 377
open findings in 44 reports (the 370 of phase 1 plus the deck and course notes
reports since), 269 of 671 files with a chapter (40 %), 64 chapters due, no dated
fact due, 4 decks with an upcoming session, 6 past INTRA decks left out. It finds 11
decks with every chapter, not the hand measurement's 13: that one rounded
sparks-formation/pav and pyp's 99 % up (each lacks
`python/basics/control-structures/control-structures-advanced`).

### 6. The studioz page

A page reading `deckz dashboard --json` (studioz imports only read-only APIs), each
row linking to its report, deck or chapter. `docs/architecture/studioz.md` gets what
deckz keeps stable for it.

**Settled 2026-11-08 (the maintainer), nothing coded yet:**

- *Where:* a new tab of its own (the panel's tabs are Problèmes, Construction,
  Tâches: a fourth beside them, unless the code shows a better place; say so first).
- *Links:* the maintainer prefers the **chapter**: a row opens the course notes
  chapter it is about in the editor (`static/editor.js`; `studioz.sources` already
  edits `.md`, so `supports/` chapters open). Settle first what that is for a deck row
  (its chapters due under a rule? its missing ones, which don't exist yet?) and a
  section row (several chapters), and the fallback when no chapter applies (the
  report, the deck page).
- *What's shown:* the totals, the decks as `deckz dashboard` orders them, and every
  section that needs care (`SectionRow.needs_care`, by score; no cap of 15, the page
  scrolls), never the fresh ones. Past INTRA decks are left out by the CLI's rule (no
  upcoming session; without the calendar, a claimed start over 31 days old): the page
  runs `deckz dashboard --json` without `--all`, and shows `left_out`'s count.
- *When:* on demand only. A button runs the workspace's own `deckz dashboard --json`
  (about 15 s on slides; as `studioz.background` or `studioz.jobs` runs slow commands,
  whichever fits) and the tab shows the result with when it was computed, until the
  next run. Nothing runs it by itself: not a file change, not the tab opening.
- No client name: the JSON has none (sessions carry dates only); keep it so.

### Later

A history (the JSON of each `deckz worktree land`, in the user's state directory) for
trends. Not before the rest is used.

## Acceptance

On slides, the dashboard reproduces the 2026-11-08 measurement (slides' plan), except
where that measurement guessed (the hierarchy pass, the unreadable outcomes), and the
maintainer reads their maintenance from it without asking an agent.
