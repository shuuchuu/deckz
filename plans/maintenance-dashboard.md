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

### 3. Rule dates and dated facts

- `review.rules`: `[{paths: <glob>, since: <date>, why: <text>}]`. A file marked before
  `since` is *due* (a fourth state beside fresh/stale/unreviewed, shown with `why`).
  Slides' first one: `supports/**`, 2026-10-23, the hierarchy rules
  (`dff3788f`).
- `review.dated_facts`: the fast-moving sections and the two delays (slides: 6 and 12
  months), moving `qa-dated-facts` from slides' `tools/checks.py` into deckz (slides
  then drops its own and keeps the opt-in name).

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

### 5. The command

`deckz dashboard [--json]`, a read-only aggregate of the above:

- totals: sections with a report (fresh, stale, partial, none), files, open findings
  by rubric, course notes coverage, chapters due by rule;
- per section: decks, state, open findings, dated facts due;
- per deck: the five levels, course notes coverage, chapters due, next session;
  sorted by next session, then by the review score `review status` already uses;
  past INTRA decks with no upcoming session left out unless `--all`.

### 6. The studioz page

A page reading `deckz dashboard --json` (studioz imports only read-only APIs), each
row linking to its report, deck or chapter. `docs/architecture/studioz.md` gets what
deckz keeps stable for it.

### Later

A history (the JSON of each `deckz worktree land`, in the user's state directory) for
trends. Not before the rest is used.

## Acceptance

On slides, the dashboard reproduces the 2026-11-08 measurement (slides' plan), except
where that measurement guessed (the hierarchy pass, the unreadable outcomes), and the
maintainer reads their maintenance from it without asking an agent.
