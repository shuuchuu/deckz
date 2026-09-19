# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`deckz` is a CLI tool (Python, `src/deckz`) for managing a large number of
Beamer LaTeX decks shared by several people, with slides ("sections") shared
across decks. It is not usable out of the box on an arbitrary repository: it
enforces strong conventions on the layout of the repository it *operates on*
(a separate, unrelated git repo containing `deckz.yml`, `variables.yml`,
`shared/`, per-company/per-deck directories, etc. — see README.md for the
full layout). Keep this distinction in mind: "the repo" (this codebase) vs.
"a deckz-managed repo" (what the tool acts on at runtime).

## Commands

Dependency management and running: this project uses `uv`; run tools via
`uv run <tool>`.

- Lint + format-check + typecheck: `uv run doit check` (or individually:
  `uv run ruff check src/deckz tests`, `uv run ruff format --check src/deckz tests`,
  `uv run ty check src/deckz tests`)
- Tests: `uv run doit test` or `uv run pytest`
  - Single test: `uv run pytest tests/test_cli.py::test_name`
- Default doit task (`uv run doit`) runs `check` only, not `test`.
- Install the git pre-commit hook (runs `uv run doit check test` before
  every commit): `uv run doit install_hooks`. `bumpver`'s own, unrelated
  `pre_commit_hook` setting (`[bumpver]` in `pyproject.toml`) runs
  `scripts/bumpver_pre_commit.sh` during `bumpver update` itself (to keep
  `uv.lock` in the same commit as the version bump) — it's not a git hook
  and isn't affected by `install_hooks`.
- Docs: built with `mkdocs` from docstrings (see `mkdocs.yml`, `docs/`).
- Version bumps: `bumpver` (see `[bumpver]` in `pyproject.toml`); do not hand-edit
  the version strings it manages in `pyproject.toml` / `src/deckz/__init__.py`.

## Architecture

### CLI wiring

`src/deckz/cli/__init__.py` creates the single `cyclopts` `App` and, in
`main()`, calls `import_module_and_submodules` to import every module under
`deckz.cli` — each command module registers itself onto the shared `app` via
`@app.command()` as an import side effect (e.g. `src/deckz/cli/upload.py`).
Related commands are grouped under sub-apps: most are their own package
under `src/deckz/cli/` with one module per subcommand (`run`, `check`,
`clean`, `show`, `flavor`, `asset`, `i18n`, `extras` — see `run/__init__.py`
for the pattern: an `App(name=...)` registered onto the parent app);
`watch.py` instead defines its subcommands directly in a single module. A
sub-app may declare a default subcommand via `@app.default`
(`run`/`show`/`clean` do; `check` deliberately doesn't, since its
subcommands' costs differ too much to pick one safely). Command functions
themselves stay thin: they parse CLI args, build a `DeckSettings`/
`GlobalSettings`, and delegate to `src/deckz/pipelines.py`,
`src/deckz/checking.py`, or an `analyzing/*` module — no business logic
lives in the `cli/` layer.

### Settings resolution

`configuring/settings.py` defines `GlobalPaths`/`DeckSettings`/`GlobalSettings`
(Pydantic models). Paths are built from a small template-like mechanism:
fields declared as raw strings like `"{git_dir}/shared"` are resolved against
already-computed sibling fields via a custom `BeforeValidator`
(`_convert`/`_Path`). `deckz.yml` and `variables.yml` are looked up and
merged from three locations, in order: the target repo's git root, the
user's XDG config dir, and the current directory up to the git root (see
`utils.dirs_hierarchy` / `load_all_yamls`). `GlobalSettings` covers
repo-wide operations (e.g. `check decks`, asset building); `DeckSettings`
extends it for operations scoped to a single deck (the current working
directory must be inside a deck).

### Components + factories (dependency injection)

`components/protocols.py` defines `Protocol` classes for every major piece
(`ParserProtocol`, `DeckBuilderProtocol`, `CompilerProtocol`,
`RendererProtocol`, `AssetsBuilderProtocol`, etc.), and
`components/factory.py` provides `GlobalSettingsFactory` /
`DeckSettingsFactory` as the construction points — they lazily import and
instantiate the concrete implementation (`components/parser.py`,
`components/deck_builder.py` / `incremental_deck_builder.py`,
`components/compiler.py`, `components/renderer.py`, etc.) wired up with
paths/settings. Call sites depend on the protocol/factory, not on concrete
classes directly, so new implementations only need to be plugged in at the
factory. `DeckSettingsFactory.deck_builder()` picks between
`DeckBuilder` and `IncrementalDeckBuilder` based on
`settings.incremental_compilation`.

### Build pipeline

`pipelines.py` holds the orchestration functions the CLI commands call
(`run`, `run_file`, `run_section`, `run_all`, `check_shared`, `check_all`,
`run_assets`, `watch`). The common path (`_build`) is: resolve variables →
build assets (tikz/plotly/plt standalones) via the assets builder → build
the deck (render Jinja2 → compile LaTeX) via the deck builder; `_build` also
takes an optional `basedirs` override, used only by `check_shared`/
`check_all` since their synthetic decks can include files living under any
deck's directory, not just one `current_dir`/`shared_dir` pair. `watch()` is
a generic file-watch-and-rerun wrapper (used by `deckz watch deck` /
`deckz watch section`), not build-specific.

`check_shared`/`check_all` (backing `deckz check shared`/`deckz check all`)
build their `Deck` purely in memory via `src/deckz/checking.py` — no yaml is
ever written to disk. They use `Parser.all_files_section()`
(`components/parser.py`) to expand a shared section to every file in its
own directory rather than a named flavor's `includes` list; `check_all`
additionally builds one extra copy of a section per deck that locally
overrides one of its files (detected by re-resolving with that deck's own
`local_latex_dir`). Both write their output to a persistent
`<git_dir>/.check/{shared,all}/` scratch directory (`checking.check_scratch_dir`),
since these decks have no real deck directory of their own; `deckz run
file`/`deckz run section` use the same convention under `<git_dir>/.run/`,
to avoid polluting a real deck's own `pdf`/`.build`. `deckz clean all`
sweeps both.

### Data model

`models.py` defines the deck domain model: `DeckDefinition`/`Deck`,
`PartDefinition`/`Part`, section/flavor includes, and the
`ResolvedPath`/`UnresolvedPath` distinction used when resolving shared vs.
local LaTeX file/section references. `Parser` (`components/parser.py`)
turns YAML deck/section definitions into this model; the rest of the
pipeline operates on the model, not on YAML directly.

### Analyzing

`analyzing/` holds repository-wide, read-only analyses that don't fit the
build pipeline: flavor renaming/merging, section search, i18n
(fr/en) consistency checks. These back the `deckz deps`,
`deckz search-sections`, `deckz section-flavors`, `deckz section-files`,
`deckz flavor rename`, `deckz flavor deduplicate`, and `deckz i18n *`
commands.

### Extras

`src/deckz/extras/` holds the business logic for `deckz extras`'s
subcommands (`github_querying.py` for `issue`, `mailing.py` for `random`,
`labs.py` for `labs`) plus `uploading.py` for the top-level `deckz upload`
— side commands unrelated to the build pipeline, each with its own thin
`cli/extras/*.py` (or `cli/upload.py`) wrapper, same split as everywhere
else in `cli/`.

## Conventions

- ruff config selects an explicit rule set (see `[tool.ruff.lint]` in
  `pyproject.toml`) with `preview = true`; docstrings follow Google
  convention and undocumented-code rules (`D1`) are ignored.
- Type checking is done with `ty` (not mypy), scoped to `src/deckz tests`.
