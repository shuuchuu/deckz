# Setting up

## A fresh clone

1. Install [uv](https://docs.astral.sh/uv/) and run `uv sync` in the repository (if
   the repository installs deckz from a sibling checkout, clone deckz next to it
   first: its `pyproject.toml` says so under `[tool.uv.sources]`).
2. Run `deckz setup` (or `uv run deckz setup` until your shell finds `deckz`).

`deckz setup` checks what deckz and the repository need, and does what can be done
for you:

- deckz itself, when it runs from a git checkout (the sibling checkout above): one
  behind its upstream branch is reported with the `git pull` to run, since the
  repository may rely on fixes newer than your copy;
- the clone of the data sets repository the course notes link to, when `deckz.yml`
  names one (`course_notes.code.datasets`): a missing one is reported with the `git
  clone` to run, one behind its upstream with the `git pull`;
- the executables (git, pandoc, and those the repository lists in `deckz.yml`'s
  `setup.requires`): a missing one is reported with how to install it;
- the git hooks, which check every commit (see [Before committing](before-you-commit.md));
- the git remotes the repository lists in `deckz.yml`'s `setup.remotes`, e.g. those
  the labs and videos are published to: a missing one is added;
- the repository's own setup steps (`setup.steps`), e.g. downloading the JavaScript
  the HTML decks need;
- the videos never rendered: reported, since a render takes minutes. `deckz setup
  --videos` renders them.

It exits with an error while something is missing, and is safe to run again: after
each `git pull` is a good habit. `deckz setup --check` only reports.

If you work with Claude Code, `deckz setup --claude` also installs the hooks that keep
an agent from skipping the checks or discarding other people's work.

## The `.env` file

A `.env` file sets your own defaults for `deckz run` and the commands processing
several languages, and the credentials some commands read (e.g. a lab's token). Put it
in deckz's config directory, `~/.config/deckz/.env`, where every checkout reads it; a
git-ignored `.env` at a checkout's root overrides it for that checkout only. E.g.:

```sh
DECKZ_LANG="fr en"
DECKZ_RUN_PRESENTATION=false
DECKZ_RUN_PRINT=false
```

Every `deckz run` starts by saying what it builds and which of these values it used,
so a default you forgot about never goes unnoticed. `deckz run --all` ignores them, but
for `DECKZ_RUN_SYNC`, to build everything (see [Editing](editing.md#a-real-build)).

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
rebuilt for hours), then `deckz setup` runs there (its own Python environment, for
instance, which takes a second). `add` fails only when the worktree lacks something
of its own (a setup step that failed, its git hooks); what every checkout lacks alike
(a tool your machine doesn't have, a video never rendered) is listed, and the
worktree is ready all the same. Afterwards, a figure or a video missing or out of
date in one checkout but up to date in another, for the same sources, is copied from
there when a build or a render needs it: render a video in the main checkout, publish
it from a worktree. The worktree shares nothing else with the main
checkout but git's history: your `~/.config/deckz/.env` applies to both. `remove`
refuses while the worktree holds work nothing else has, and lists it.

What the worktree built outlives it. `deckz worktree land` and `remove` copy into the
main checkout the figures and videos it lacks; `remove` sets aside, in the
repository's git directory, those the main checkout has built from other sources
(it says which), and the main checkout's next build or render takes them once its
sources match the worktree's: after a pull of the worktree's work. `deckz setup`
drops them once a checkout holds them, or after 30 days.

## Unattended agent sessions, one per block

A plan done block by block by an agent (a night of reviews) is best done by a fresh
Claude Code session per block: one session doing them all carries every past block in
its context. `deckz agent loop` starts them one after another:

```sh
deckz agent loop "Reprends docs/plans/<plan>.md, file C, un seul bloc" --model fable
```

Each session runs `claude -p` at the repository's root, in Claude Code's `auto`
permission mode (`--permission-mode`), does one share of the work, records it where
the plan tracks progress, and ends its last message with `DECKZ-LOOP: continue`,
`done` or `stop <why>`: instructions appended to the prompt ask for it. The loop
stops at the first `done` or `stop`, at a session that fails (a usage limit, say) or
gives no such line, and after `--max-sessions` (20). Each session's result is kept
under `.run/agent-loop/<start time>/`, and `claude --resume <session id>` (logged as
each session ends) reopens one. It exits 1 unless the last session said `done` or
`continue`.

A usage limit stops a session in the middle of its share, its edits uncommitted, and
the loop with it. With `--wait-on-limit`, the loop sleeps until the limit resets (the
time its message gives, "resets 9pm"), then reopens that same session (`claude
--resume`), which goes on from where it stopped: a fresh session wouldn't know what
the uncommitted edits are. It waits 6 hours at most, so a weekly limit still stops
the loop. Several loops on one account share its limit: they all stop at the same
time, and all go on at the reset.

Where agents must work in a worktree (`worktree.required_for_agents`), start the loop
in it, `--workdir ../<repository>--<name>`: a headless session can't enter an existing
worktree by itself (Claude Code's EnterWorktree asks for a confirmation no one gives)
and stays in the main checkout, where the hooks deny its edits. The results are then
under that worktree's `.run/agent-loop/`, and `claude --resume` runs from it.
