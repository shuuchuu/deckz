# Setting up

## A fresh clone

1. Install [uv](https://docs.astral.sh/uv/) and run `uv sync` in the repository (if
   the repository installs deckz from a sibling checkout, clone deckz next to it
   first: its `pyproject.toml` says so under `[tool.uv.sources]`).
2. Run `deckz setup` (or `uv run deckz setup` until your shell finds `deckz`).

`deckz setup` checks what deckz and the repository need, and does what can be done
for you:

- the executables (git, pandoc, and those the repository lists in `deckz.yml`'s
  `setup.requires`): a missing one is reported with how to install it;
- the git hooks, which check every commit (see [Before committing](before-you-commit.md));
- the repository's own setup steps (`setup.steps`), e.g. downloading the JavaScript
  the HTML decks need;
- the videos never rendered: reported, since a render takes minutes. `deckz setup
  --videos` renders them.

It exits with an error while something is missing, and is safe to run again: after
each `git pull` is a good habit. `deckz setup --check` only reports.

If you work with Claude Code, `deckz setup --claude` also installs the hooks that keep
an agent from skipping the checks or discarding other people's work.

## The `.env` file

A git-ignored `.env` at the repository's root can set your own defaults for `deckz
run` and the commands processing several languages, e.g.:

```sh
DECKZ_LANG="fr en"
DECKZ_RUN_PRESENTATION=false
DECKZ_RUN_PRINT=false
```

Every `deckz run` starts by saying what it builds and which of these values it used,
so a default you forgot about never goes unnoticed.

## A second checkout for a separate piece of work

To work on something apart (a new deck while another is half-edited, or to let
someone else's uncommitted work be), open a worktree: a second checkout of the
repository, on its own branch, next to the first.

```sh
deckz worktree add pnd-2026     # creates ../<repo>--pnd-2026 on branch ws/pnd-2026
cd ../<repo>--pnd-2026          # build, edit and commit there as usual
deckz worktree list             # each worktree's uncommitted changes and unpushed commits
deckz worktree remove pnd-2026  # once its work is committed and pushed (or merged)
```

It starts from the main checkout's current commit (`--base` picks another), with
the main checkout's builds copied in (rendered figures and videos, so nothing is
rebuilt for hours), and its `.env` (and the Python environment, while the
dependencies are the same) shared. `remove` refuses while the worktree holds work
nothing else has, and lists it.
