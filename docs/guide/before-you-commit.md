# Before committing, teaching, publishing

## `deckz status`

```sh
deckz status
```

says where your work stands, item by item, each with what to do:

- the content checks' problems (`--no-checks` skips them, the slow part);
- what your changes leave to translate, what fails the English build of the decks
  they reach (a file with no `en/` version, a title with no `en:`), and the
  repository's translation backlog;
- lab notebooks and videos not published as committed or rendered (compared with
  the published ones as last fetched; `--fetch` fetches them first), and the demos
  you changed whose code no longer matches their outputs;
- the PDFs of the decks your changes reach that don't match them anymore;
- with `review.dir` set, the content of those decks never reviewed, or changed since
  its review (see [Reviews](reviews.md));
- the content files of those decks with no course notes chapter, once a deck has
  course notes in a language: at least half of its files (those not skipped) have
  their chapter in it (`deckz show course-notes --workdir <deck>` lists them).

"Your changes" are your uncommitted files plus the commits you haven't pushed
(`--since <revision>` to look further back).

```sh
deckz status <deck>
```

says instead what's left before teaching or uploading one deck, whoever made it: the
checks' problems in its files (deferred ones included: they're due now), what fails
its English build, its files waiting for a port to the other language, and its built
PDFs that don't match its
content, with their shrunk frames and header or footer lines that wrap, and how many
of its content files aren't reviewed at their current version, and, once it has course
notes, its content files with no chapter.

## Committing

Stage the files you changed (`git add <files>`) and commit. Two git hooks run:

- **pre-commit** runs the content checks on what you're committing (see
  [Checks](checks.md)). It refuses the commit only for a blocking check's problem
  (a secret in a notebook, a broken Jinja tag or deck definition); fix it, and
  commit again. The other problems it prints can wait until you publish or teach;
  `deckz status` keeps listing them;
- **commit-msg** marks a commit changing one language of a pair only `Lang-sync:
  pending`, unless you said there's nothing to port (see
  [Translating](translating.md)).

Never skip them (`--no-verify`): CI runs the same checks on every push anyway.

## Teaching

Build the deck you'll hand out (`deckz run --workdir <deck> --lang fr` or `en`), look
at `deckz status <deck>`, and skim the PDF. `deckz upload` sends a deck's PDFs to
Google Drive; it refuses PDFs that don't match the deck's content anymore (rebuild
them with `deckz run --all`, or delete them), and refuses while a check reports a problem in the deck's
files, even one that didn't block its commit (fix it, or `--skip-checks`).
`deckz upload --dry-run` lists the PDFs it would send, the outdated ones and the
deck's problems, without connecting.

## Pushing

```sh
deckz push --dry-run   # what would be pushed, and what's left to publish
deckz push             # push it
```

pushes, in this order, what your work leaves local:

1. the deckz checkout you run deckz from, when it's one (`../deckz`): its branch, if
   ahead of its remote;
2. the labs' own repositories (`labs.repos` in `deckz.yml`), from their clones next to
   the repository (`../<name>`, or their `clone`): every branch ahead of its remote.
   Their branches are stacked (`solution` on `main`), so a fix to `main` is rebased
   into the branches above, which then need `deckz push --force`: it force-pushes them
   with a lease, only when their remote holds nothing they didn't have;
3. the repository itself: the main checkout's branch (land a worktree first, `deckz
   worktree land`).

deckz goes first because the repository's CI installs deckz from its remote, and the
content links to the labs' repositories: pushed first, the repository would be checked
against a deckz that lacks the code it depends on. So when deckz's push fails, or its
branch has diverged, nothing else is pushed. And since the content links to the labs'
repositories' branches, when one of those repositories fails (a push refused, a branch
diverged, a rebased branch that needs `--force`), the repository isn't pushed, nor
anything published; the other labs' repositories are pushed all the same, so that you
see everything that blocks at once. A lab repository with no local clone, or none of
whose branches carries Copier answers, is only skipped, and doesn't stop the rest.
deckz's and the repository's branches are never forced: one behind or diverged is
left, with the `git pull` to run. `--dry-run` shows the same stops.

Without `--publish`, `deckz push` ends with what's left to publish.

## Publishing labs and videos

`deckz labs publish` and `deckz videos publish` update what trainees open from the
PDFs. They're the maintainer's call: once the notebooks or renders are committed and
reviewed. `deckz push --publish` runs them after its pushes, when something is left
to publish.
