# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`deckz` is a CLI tool (Python, `src/deckz`) for managing a large number of
slide decks shared by several people, with slides ("sections") shared
across decks. Decks compile with Typst: a `.typ` main template plus
Markdown content converted by pandoc (LaTeX/Beamer support was removed after
28.x). It is not usable out of the box on an arbitrary repository: it
enforces strong conventions on the layout of the repository it *operates on*
(a separate, unrelated git repo containing `deckz.yml`, `variables.yml`,
`content/` (shared sections), `assets/`, `templates/`,
per-company/per-deck directories, etc. — see README.md for the
full layout). Keep this distinction in mind: "the repo" (this codebase) vs.
"a deckz-managed repo" (what the tool acts on at runtime).

## Commands

Dependency management and running: this project uses `uv`; run tools via
`uv run <tool>`.

- Lint + format-check + typecheck + layers: `uv run doit check` (or individually:
  `uv run ruff check src/deckz tests`, `uv run ruff format --check src/deckz tests`,
  `uv run ty check src/deckz tests`, each also covering `studioz/src studioz/tests`;
  and `uv run lint-imports`, the import-linter contracts of `[tool.importlinter]`
  in `pyproject.toml`: deckz's layers, only the CLIs import `rich`/`cyclopts`,
  concrete components come from the factories, deckz and studioz's boundary)
- Tests: `uv run doit test` (runs `pytest -n auto`, parallel via pytest-xdist)
  or `uv run pytest` (serial)
- Default doit task (`uv run doit`) runs `check` only, not `test`.
- Install the git pre-commit hook (runs `uv run doit check test` before
  every commit): `uv run doit install_hooks`. `bumpver`'s own, unrelated
  `pre_commit_hook` setting (`[bumpver]` in `pyproject.toml`) runs
  `scripts/bumpver_pre_commit.sh` during `bumpver update` itself (to keep
  `uv.lock` in the same commit as the version bump) — it's not a git hook
  and isn't affected by `install_hooks`.
- Docs: built with `mkdocs` from docstrings (see `mkdocs.yml`, `docs/`):
  `docs/guide/` for the people running a deckz-managed repository,
  `docs/architecture/` for those working on deckz, the code reference generated.
- Plans: a plan for a multi-step change goes in `plans/`, and moves to
  `plans/archive/` once finished (what is left is only the user's to do:
  push, release).
- Version bumps: `bumpver` (see `[bumpver]` in `pyproject.toml`); do not hand-edit
  the version strings it manages in `pyproject.toml` / `src/deckz/__init__.py`, and
  studioz's (`studioz/pyproject.toml`, its pin on deckz, `studioz/src/studioz/__init__.py`).
- studioz's JavaScript: `uv run doit vendor` (`npm ci` in `studioz/`, then copies the
  pinned files into `studioz/src/studioz/static/vendor/`, which is committed, and
  bundles the CodeMirror modules `studioz/codemirror.mjs` lists with esbuild).
  Pin a new package with `npm install --save-exact --before=<two weeks ago>`, so
  that its dependencies are no newer either.

### This working tree is live

shuuchuu/slides installs deckz as an editable dependency from `../deckz`, so this
working tree is the deckz every slides session runs: its `deckz` commands, its git
hooks and its Claude Code hooks. A half-done edit (an import error, a changed default)
breaks or changes them at once, for sessions you can't see. So change code in a git
worktree (`git worktree add ../deckz-<topic>`), test it there, try it on slides from a
scratch environment that has slides' dependencies and the worktree's deckz, and merge
into this checkout only a finished change. Before merging one that changes behavior
(what a build deletes, a check's verdict), tell the running slides sessions
(`ListAgents`, `SendMessage`). Docs-only edits can be made here directly.

## Architecture

`docs/architecture/` is the reference: read its page before changing a part of deckz.

| Page | Covers |
|---|---|
| `index.md` | The layers, the rules and their import-linter contracts, the known exceptions |
| `cli.md` | `deckz.cli`: command registration, the error boundary (`main`/`_launch`), stdout vs stderr, `.env` and `DECKZ_*` defaults, testing `main` |
| `tasks.md` | `status`, `setting_up`, `scaffolding`, `ci_report`, the Claude Code hooks, `hooks_install` |
| `pipelines.md` | `pipelines` (targets, plan vs build, locks, stale PDFs, `watch`), `checking`, `course_notes` |
| `analyzing.md` | The analyses, the content checks (blocking/deferred, the gates), fr/en pairing and `Lang-sync` |
| `components.md` | Protocols and factories, each component, the deck builder's outputs, Typst workers |
| `libraries.md` | `labs`, `videos`, `extras`, `worktrees`, `commits`, `remotes` |
| `foundations.md` | `configuring`, `models`, `exceptions`, `utils`, `stamps`, `drive_links` |
| `plugins.md` | What a managed repository plugs in (`templates/*.py`, `deckz.yml` commands), what it imports from deckz |
| `studioz.md` | How studioz uses deckz, and what deckz keeps stable for it |
| `state.md` | What deckz writes where, freshness, locks, processes |

The rules that shape every change:

- **Layers.** A module imports only from its own layer or below
  (`[tool.importlinter]` in `pyproject.toml`, run by `uv run doit check`). The
  contract is exhaustive: a new module fails it until it has a layer.
- **Thin CLI, silent core.** A command parses its arguments, builds a
  `GlobalSettings`/`DeckSettings`, calls one core function and renders the result.
  The core never prints or exits: it reports progress through a
  `ProgressReporterProtocol` and fails by raising a `DeckzError` whose message names
  the fix. stdout carries results only.
- **Factories.** Components come from `GlobalSettingsFactory`/`DeckSettingsFactory`,
  typed with their protocols.
- **Frozen data.** The `Deck` tree and the settings are never mutated: a variant is
  a copy (`dataclasses.replace`, `with_output_dirs`).
- **Plugins** from the managed repository load only through `load_hook`. What the
  managed repository imports from deckz is its public API (`plugins.md`).
- **studioz** runs the workspace's own `deckz` and imports only read-only APIs. A
  rule it needs goes into deckz. Its own architecture is in `studioz/CLAUDE.md`, and
  its plan in `plans/studioz.md`.

Keep `docs/architecture/` up to date in the same change as the code. A change that
adds, moves or removes a module (its layer, in the contract and the diagram), adds a
dependency between layers or a known exception (`ignore_imports`, and the table of
`index.md`), changes what a component owns on disk, a lock or a process boundary,
changes what the managed repository plugs in or imports, or changes what studioz
relies on (`--json` outputs, `watch`'s log messages), updates the pages it makes
wrong. The pages describe responsibilities and boundaries; details of one function go
in its docstring, which the code reference renders.

## Operability guidelines

deckz is how people run a deckz-managed repository, with or without an AI
agent: a contributor who never uses one must be able to do every routine
task from `deckz --help` and the docs (`plans/archive/operability.md`
records how it got there). Keep new tooling in line with that:

- **One path for people and agents.** An agent runs the same commands a
  person would. A workflow that exists only as a skill's list of steps is a
  missing command.
- **Where a rule goes**, in this order: a check that fails
  (`analyzing/content_checks.py`, or the repo's `templates/checks.py`) or a
  refusal at the point of harm (as `labs publish` refuses to drop a
  published ID); otherwise a safe default, or a task-level command that does
  the right thing; otherwise the human docs. A skill holds only judgment and
  orchestration, and points to the docs instead of restating them. An
  agent's memory never holds a repository rule.
- **Protect the repository where every contributor passes:** the git hooks
  and CI. Claude Code hooks are for the risks only agents create (several
  sessions sharing one checkout), never the only guard.
- **No destructive default, no silent setting.** An option that deletes,
  overwrites or publishes is off by default, or limited to what the run
  itself made obsolete. A value taken from the environment or `.env` is
  announced.
- **Every failure names its fix**: the command to run, or the edit to make.
- **No "remember to" steps.** A manual step that must follow a command
  becomes part of it, or a hook the repository declares in `deckz.yml` (like
  `labs.gpu.hooks`).
- **Rationale lives next to the thing.** An intentional oddity is explained
  where it is (a comment, a notebook cell, the config key), so nobody,
  person or agent, "fixes" it.
- **Generic in deckz, specific in the repository.** deckz knows the
  conventions it owns (layout, sections, labs, i18n, checks); a repository's
  own tools, theme and house rules come in through `deckz.yml` and the
  `templates/` plugins.
- **Shipping a command** means: its place in a task group of `--help`, its
  page in the docs, `--plain`/`--json` when a script or an agent reads its
  output, and tests.
