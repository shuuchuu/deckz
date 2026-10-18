# Before committing, teaching, publishing

## `deckz status`

```sh
deckz status
```

says where your work stands, item by item, each with what to do:

- the content checks' problems (`--no-checks` skips them, the slow part);
- what your changes leave to translate, and the repository's translation backlog;
- lab notebooks and videos not published as committed or rendered (compared with
  the published ones as last fetched; `--fetch` fetches them first);
- the PDFs of the decks your changes reach that don't match them anymore.

"Your changes" are your uncommitted files plus the commits you haven't pushed
(`--since <revision>` to look further back).

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
at `deckz check overflow <deck>`, and skim the PDF. `deckz upload` sends a deck's PDFs
to Google Drive; it refuses PDFs that don't match the deck's content anymore (rebuild
them, or delete them). `deckz upload --dry-run` lists the PDFs it would send and the
outdated ones, without connecting.

## Publishing labs and videos

`deckz labs publish` and `deckz videos publish` update what trainees open from the
PDFs. They're the maintainer's call: once the notebooks or renders are committed and
reviewed.
