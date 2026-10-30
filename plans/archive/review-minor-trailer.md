# Review-minor plan: a commit trailer that keeps a reviewed file fresh

**Abandoned (2026-10-30), not implemented.** Marking was never the costly part: a
small diff is read in minutes and then `deckz review mark` is one command. The cost was
the review around it: slides' `qa-section` ran its whole first-pass procedure (the
audiences table, subagents, builds, flavor fit) for a two-line diff. The fix went
there instead: `qa-section` has a follow-up mode for small diffs (≤ 3 frames and ≤ 30
lines) plus a periodic check for out-of-date facts, and deckz counts the frames a stale
file's changes touch (`FileReview.changed_frames`), which the ranking uses instead of
all of the file's frames. The data below still supports that: 12 of the 28 small
diffs carried claims, so they had to be read anyway.

## Why

`deckz review` calls a file stale as soon as its blob differs from the one a report
recorded. Every edit, even a renamed tool or a link moved to a filter, sends the file
back to the review queue until someone runs `deckz review mark <report> <file>`,
which needs the right report and is refused for changes that came through the main
branch (`changed_elsewhere`). deckz already records commit-level decisions as trailers
(`Lang-sync`, `Lang-synced`, `Lab-outputs-current`, `commits.py`): the author of a
minor edit could say so in the commit that makes it.

## What the data says (slides, main at 07fa180e, 2026-10-30)

Measured with a read-only script over every report's marks
(`analyzing.review.review_files`, then `git log` back to the recorded blob):

- 763 recorded files: 735 fresh, 28 stale, 0 unreadable reports. Each stale file's
  recorded blob is in its history (none was marked uncommitted and changed before
  committing). 26 stale files have 1 commit since their mark, 2 have 2.
- 7 commits stale them. `d008d80a` (ty → pyrefly in the slides) alone stales 17. The
  qa-fix commit `db0a205d` touches 241 files and stales only 2: qa-fix marks what it
  fixes, so the friction comes from cross-cutting commits outside a QA pass.
- Size since the mark: 16 files ≤ 5 changed lines, 6 more ≤ 10, 5 ≤ 20, 1 at 32.
- Judged by reading each diff, about 16 of the 28 need no review: tool renames
  (`ty` → `pyrefly` alone in `functions.md`, `variables.md`, `conclusion.md`,
  `typing/misc.md`, `typing/quiz.md`…, at most 8 lines), links moved to the
  `lab_links`/`lab_repo` filters, a duplicated line dropped. The other 12 carry
  new claims, some in very small diffs: `python/basics/errors.md` (2 lines, drops a
  "since 3.10, modules since 3.12" claim), `rl/intro-light.md` (a new sentence next
  to an image width change), and in the same pyrefly commit,
  `typing/basics.md` and `typing/quiz-protocols.md` (new statements about what
  pyrefly infers and reports) and `typing/intro.md` (new tool output).

Two consequences for the design:

1. **Size doesn't separate minor from substantive.** A 2-line factual fix needs review,
   a 6-line rename doesn't. The author's declaration decides; a size cap only bounds
   the damage of a wrong one.
2. **A trailer for the whole commit is too coarse.** The commit that renamed `ty` in
   10 files also made new claims in 3 of them. Declaring files one by one is what
   would have kept those 3 stale.

## Decisions

- **Trailer `Review-minor: <path>`**, repeatable, naming a file or a directory (all
  the files under it the commit changes). It covers the commit's change to that path
  only. There is no form for the whole commit (see above). The reason goes in the
  commit body, as for any commit. Validated by the `commit-msg` hook at commit time
  (the staged diff) and by `deckz hooks check-commits` in CI, like `Lang-sync`:
  - the path names something the commit changes (a typo would cover nothing);
  - the change to each covered file is at most `review.minor_max_lines` changed lines
    (added + removed, `deckz.yml`, default 10: the clearly minor diffs measured are
    at most 8). Above it the hook refuses the commit, and the message names the fix:
    drop the trailer for that path, or split the commit.
- **A new state, `minor`.** A stale file is `minor` when all three hold:
  - every commit between its recorded blob (the most recent commit whose version
    of the file is the recorded blob, walking back from HEAD) and HEAD has a
    `Review-minor` trailer covering it;
  - the working tree equals HEAD for that file;
  - the lines those commits changed add up to at most `review.minor_max_lines`,
    since minor edits accumulate (ten of them make a rewrite).
  Otherwise it stays `stale`, and `review status` says why (one commit without the
  trailer, uncommitted changes, or the cap reached). If the recorded blob is not in
  the history (marked uncommitted, then changed), the file is `stale`.
- **`minor` counts as reviewed, and stays visible.** The ranking, `deck_counts`
  (`deckz status`), `deckz labs`/`agent_checkouts` and studioz treat it like
  `fresh`. `review status` shows it apart (`minor: 2 commits, +4/−3`), and
  `review diff` still shows its diff since the mark, so the next real review reads
  it. `review mark` with no paths refreshes it like any recorded file, which ends the
  `minor` state.
- **`mark` accepts minor changes from elsewhere.** A change from the main line that
  is entirely covered by `Review-minor` trailers doesn't need `--accept`: its author
  declared it. Any other change from elsewhere is still refused.
- **History is read only for stale files**, one `git log` per file
  (`--format=%H%x00%B`, stopping at the recorded blob), cached for one command.
  There are 28 stale files today, so this adds no noticeable cost to `deckz status`.
- **Not for QA fixes.** A fix of a QA finding is reviewed through `review diff` +
  `mark` (qa-fix already does). The slides docs and the qa-fix skill say so: the
  trailer is for edits that change no claim (renames, links, typography, image
  sizes, layout).

## Rejected

- **Verifying a declared substitution** (`Review-minor: s/ty/pyrefly/`, with deckz
  checking that the diff is exactly that substitution): it doesn't depend on trust,
  but covers only 6 of the 16 minor files measured. List reorders, link filters and
  dropped lines don't fit it.
- **A size threshold alone, no trailer**: see "What the data says", point 1.
- **`deckz review mark` finding the report itself** (`--minor`): still writes the
  shared report headers, and still hits `changed_elsewhere`. It may be worth doing
  anyway as a convenience (`mark <file>` when exactly one report records it), but
  that is a separate change.

## Steps

Code in a worktree (`git worktree add ../deckz-review-minor`), tried on slides from a
scratch environment before merging; tell the slides sessions before merging, since
`review status`, `deckz status` and the hooks change behavior.

1. `commits.py`: `review_minor_paths(message)`; `settings`: `review.minor_max_lines`.
   Tests.
2. `analyzing/review.py`: the history walk, the `minor` state on `FileReview` (with
   its commits and line counts, and why a file is not `minor`), `deck_counts`,
   `ranking` and `changed_elsewhere`/`mark` updated. Tests on a scratch repository:
   one minor commit, two, one without the trailer, a directory path, the cap reached
   by accumulation, uncommitted changes, recorded blob absent from history, a minor
   change from the main line.
3. CLI: `review status` (text and `--json`: the new state is part of the studioz
   contract, `docs/architecture/tasks.md`), `review diff` labels minor commits.
   Check every consumer of the states: `status.py`, `agent_checkouts.py`,
   studioz's backlog.
4. Hooks: `check_commit_msg` validates the trailer against the staged diff,
   `check_commits` in CI; refusal messages name the fix. Tests.
5. Docs: `docs/guide/reviews.md` (the trailer, the state, when not to use it),
   `before-you-commit.md`, the agent notes (`generate_agent_notes.py`).
6. slides (its own worktree): `docs/conventions.md` "Relecture (QA)" and
   `HANDBOOK.md` in French, `docs/decisions.md` (why per-path and capped, with the
   data above), the qa-fix and qa-section skills (not for QA fixes); regenerate the
   CI workflow if `deckz hooks install --ci` changes it.
7. Try it on slides: the 16 minor files above can't take the trailer after the
   fact, since their commits are on main. Refresh them with `review mark` once, and
   check that a new rename commit with the trailer leaves them `minor`.

## Open questions for the user

- The cap's default (10 changed lines per file, cumulative since the mark).
- Whether `mark` should accept main-line changes covered by the trailer without
  `--accept` (proposed: yes).
