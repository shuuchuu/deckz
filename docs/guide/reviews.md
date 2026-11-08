# Reviews

Shared content is included by many decks: a file reviewed once is reviewed for all of
them, as long as nobody changes it since. `deckz review` keeps track of that. It knows
which version of each file was reviewed, which files changed since, and what changed,
so the next review reads the diff rather than the whole file.

It needs a directory for the review reports, in `deckz.yml`:

```yaml
review:
  dir: docs/qa
```

## Reports

A report is any Markdown file under `review.dir`, at any depth. Where it is says what
it reviews, so that a script finds a report from its path alone:

- under `sections/`, a shared section's report, one per section (e.g.
  `docs/qa/sections/python/basics.md`: two people reviewing different sections never
  touch the same file);
- at `<deck directory>.md`, a deck's report: its deck pass (e.g.
  `docs/qa/decks/orsys/pyt.md` for the deck `decks/orsys/pyt`, see
  [Deck reports](#deck-reports)).

The `review-headers` check fails on a report anywhere else, e.g. a deck's report left
behind when its deck was renamed: `git mv` it to its deck's new path.

What a report says is up to the repository: findings, summaries, decisions. Its front
matter's `reviewed` key is deckz's, written by `deckz review mark`, never by hand:

```yaml
---
reviewed:
  date: 2026-10-23
  base: 4074bddb97c3e184af56ad56084ce5e1fd80cd30
  files:
    content/python/basics/variables/variables.md: <blob sha of the version reviewed>
    labs/notebooks/python/basics/variables/exercises/hands-on-fr.ipynb: <blob sha>
---
```

Each file is recorded with the git blob sha of the version reviewed (`git
hash-object <file>`): it names a content, so it survives rebases, and `deckz review
diff` shows exactly what changed since. `base` is the commit the last mark was made
on. deckz rewrites only this key: the rest of the front matter and the report's text
stay as they are.

## Where reviews stand

```sh
deckz review status                       # every shared section, most worth reviewing first
deckz review status decks/orsys/ipy       # one deck's content files, by section
deckz review status content/python/basics # the files decks include under a directory
```

A file is **fresh** when it's at the version reviewed, **stale** when it changed since
(with the lines added and removed, and for a content file the frames those changes
touch), **unreviewed** when no report records it, and
**deleted** when a report records a file that's gone. When several reports record a
file, the most recent mark counts.

With no argument, the sections some deck uses are ranked by the number of decks
including one of their files, times their frames to review: all the frames of their
unreviewed files, and those the changes of their stale files touch (a one-line fix
in a ten-frame file is one frame to review, not ten). The top of the list is what a
review helps most. For a deck, its content files come
by section (as `deckz show paths` resolves them), then the other files (lab
notebooks, say) the reports covering them record: which notebooks go with which
slides is the repository's own convention, so deckz shows what the reports say.

`deckz status` has a **Review** section too: for each deck your changes reach (or the
deck given), how many of its content files were never reviewed or changed since,
pointing to `deckz review status <deck>`.

`--json` and `--plain` are for scripts and agents (see `deckz review status --help`).
The command always exits 0.

## Reviewing

Read the files, write the report, then record what you read:

```sh
deckz review mark docs/qa/sections/python/basics.md content/python/basics labs/notebooks/python/basics
```

This creates the report if needed (front matter only) and records the working-tree
version of each file (a content directory stands for the content files decks include
under it, not their `en/` translations; another directory for its tracked files).

Next time, read only what changed, then mark again with no path to refresh every file
the report records:

```sh
deckz review diff docs/qa/sections/python/basics.md          # the diffs since the review
deckz review diff docs/qa/sections/python/basics.md --stat   # one line per changed file
deckz review mark docs/qa/sections/python/basics.md
```

A file you edited yourself to fix what the review found is marked as well: those are
changes you've read.

### When `mark` refuses a file

`mark` refuses a file whose change since its review came from elsewhere: commits
another session or person landed on the main branch (the branch of the repository's
main checkout, or the upstream when you're on it), which reached your branch with a
rebase or a pull. Nobody reviewed those changes, so marking the file would hide them.
The other files are marked, and the command exits 1, saying what to do:

```sh
deckz review diff docs/qa/sections/python/basics.md content/python/basics/variables/operators.md
deckz review mark docs/qa/sections/python/basics.md --accept content/python/basics/variables/operators.md
```

Changes made on your own branch since an earlier mark pass. A version you marked
without ever committing or staging it can't be told apart from someone else's:
check the diff and `--accept`.

### A review made before

A review whose report was never marked (written before the repository had `review.dir`,
say) is registered at the commit it read:

```sh
deckz review mark docs/qa/decks/orsys/pyt.md --at c6985bae
```

`--at` records the versions of that commit, with its date and as its `base`, so the
files changed since show stale at once. It applies only to a report recording nothing
yet, and the commit must be in the branch's history.

### Renamed or deleted files

The `review-headers` check (run by `deckz check`, hence the pre-commit hook) fails on
a report recording a file that no longer exists, or a malformed `reviewed` key. A
rename is fixed in one call, forgetting the old path and recording the new one:

```sh
deckz review mark docs/qa/sections/python/basics.md --forget content/old.md content/new.md
```

The new path is recorded at its current version: if the file also changed, review it
first. `--forget` alone removes a deleted file.

## Deck reports

A section report reviews shared content once for every deck including it; a deck's
pass reviews what is the deck's own: whether its program is covered, its sections fit
together, its budget holds. Its report, at `<review.dir>/<deck directory>.md`, records
the deck's own files: its `deck.yml`, `variables.yml`, program and `content/`, every
file under its directory that git tracks or doesn't ignore, but not the `en/`
translations. With no path, `mark` records them all, the new ones included:

```sh
deckz review mark docs/qa/decks/orsys/pyt.md
```

The deck's directory stands for the same files there, and `mark` refuses shared
content in a deck's report: its sections' reports review it. So the pass holds while
the deck's own files are at the version it read; a change to one of its shared
sections shows in that section's report, at the content level, not in the deck's.
`deckz review status <deck>` ends with its pass: none recorded, holds, or out of date
with the files changed or added since. `deckz review findings <deck>` includes the
deck's report.

## Findings

What a report says is the repository's, but deckz can count what's left to do if the
findings follow one grammar, set in `deckz.yml`:

```yaml
review:
  dir: docs/qa
  findings:
    heading: Findings          # the heading the findings are under, at any level
    rubrics:                   # the headings one level below it, by letters
      E: Errors
      P: Pedagogy
    outcomes:                  # written emphasized: *open*
      open: open
      done: done
      refused: refused
```

A finding is a top-level list item under that heading whose text starts with its id
in bold, its rubric's letters and a number, and it sits under its rubric's heading
(deeper headings may divide a rubric). Its outcome is the last outcome word in it,
emphasized, wherever it is: after a sub-list or a blank line, followed by the commit
or the reason. Other list items (a verdict, what was checked) aren't findings:

```markdown
## Deck reports

A section report reviews shared content once for every deck including it; a deck's
pass reviews what is the deck's own: whether its program is covered, its sections fit
together, its budget holds. Its report, at `<review.dir>/<deck directory>.md`, records
the deck's own files: its `deck.yml`, `variables.yml`, program and `content/`, every
file under its directory that git tracks or doesn't ignore, but not the `en/`
translations. With no path, `mark` records them all, the new ones included:

```sh
deckz review mark docs/qa/decks/orsys/pyt.md
```

The deck's directory stands for the same files there, and `mark` refuses shared
content in a deck's report: its sections' reports review it. So the pass holds while
the deck's own files are at the version it read; a change to one of its shared
sections shows in that section's report, at the content level, not in the deck's.
`deckz review status <deck>` ends with its pass: none recorded, holds, or out of date
with the files changed or added since. `deckz review findings <deck>` includes the
deck's report.

## Findings

### Errors

- **E1** — `variables.md`, « Types »: `int` has no size limit. *open*
- **E2** — three versions of the same frame:
  - `a.md`, « Loops »;
  - `b.md`, « Loops ».

  *done* (4f2a9c1)
```

```sh
deckz review findings                  # every report, the most open findings first
deckz review findings decks/orsys/ipy  # the open findings of the reports covering a deck
deckz review findings docs/qa/sections/python  # the reports under a directory
```

For a deck, the reports are its own and those recording one of its content files; for a path
outside `review.dir`, those recording a file under it. `--json` and `--plain` list
every finding with its line, id, outcome and first paragraph. The command always
exits 0.

The `review-findings` check (blocking) fails on a finding with no outcome, an id two
findings of a report share (give the newer one the next free number: ids are never
renumbered, so other reports can cite them), letters no rubric has, and a finding
under another rubric's heading, or under none.
