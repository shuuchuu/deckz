# Reviews

Shared content is included by many decks: a file reviewed once is reviewed for all of
them, as long as nobody changes it since. `deckz review` keeps track of that. It knows
which version of each file was reviewed, which files changed since, and what changed,
so the next review reads the diff rather than the whole file.

It needs a directory for the review reports, in `deckz.yml`:

```yaml
review:
  dir: docs/qa/sections
```

## Reports

A report is any Markdown file under `review.dir`, at any depth (one per section, e.g.
`docs/qa/sections/python/basics.md`, keeps two people reviewing different sections
from touching the same file). What it says is up to the repository: findings,
summaries, decisions. Its front matter's `reviewed` key is deckz's, written by `deckz
review mark`, never by hand:

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
(with the lines added and removed), **unreviewed** when no report records it, and
**deleted** when a report records a file that's gone. When several reports record a
file, the most recent mark counts.

With no argument, the sections some deck uses are ranked by the number of decks
including one of their files, times the frames of their stale and unreviewed files:
the top of the list is what a review helps most. For a deck, its content files come
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

### Renamed or deleted files

The `review-headers` check (run by `deckz check`, hence the pre-commit hook) fails on
a report recording a file that no longer exists, or a malformed `reviewed` key. A
rename is fixed in one call, forgetting the old path and recording the new one:

```sh
deckz review mark docs/qa/sections/python/basics.md --forget content/old.md content/new.md
```

The new path is recorded at its current version: if the file also changed, review it
first. `--forget` alone removes a deleted file.
