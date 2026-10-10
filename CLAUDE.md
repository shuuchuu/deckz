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

- Lint + format-check + typecheck: `uv run doit check` (or individually:
  `uv run ruff check src/deckz tests`, `uv run ruff format --check src/deckz tests`,
  `uv run ty check src/deckz tests`; each also covers `studioz/src studioz/tests`)
- Tests: `uv run doit test` (runs `pytest -n auto`, parallel via pytest-xdist)
  or `uv run pytest` (serial)
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
  the version strings it manages in `pyproject.toml` / `src/deckz/__init__.py`, and
  studioz's (`studioz/pyproject.toml`, its pin on deckz, `studioz/src/studioz/__init__.py`).
- studioz's JavaScript: `uv run doit vendor` (`npm ci` in `studioz/`, then copies the
  pinned files into `studioz/src/studioz/static/vendor/`, which is committed).

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

### CLI wiring

`src/deckz/cli/__init__.py` creates the single `cyclopts` `App` and, in
`main()`, calls `import_module_and_submodules` to import every module under
`deckz.cli` — each command module registers itself onto the shared `app` via
`@app.command()` as an import side effect (e.g. `src/deckz/cli/upload.py`).
Related commands are grouped under sub-apps: most are their own package
under `src/deckz/cli/` with one module per subcommand (`run`, `check`,
`clean`, `show`, `flavor`, `asset`, `i18n`, `labs`, `hooks`, `worktree`,
`extras` — see `run/__init__.py` for the pattern: an `App(name=...)` registered onto the
parent app). A sub-app may declare a default subcommand via `@app.default`
(`run`/`show`/`clean` do; `check`'s default is `content`, running
every check — deckz's own content checks plus a `templates/checks.py`
plugin's, see "Checking" below — `variables` stays its own, separate
subcommand since it's a different, slower kind of analysis). Command
functions
themselves stay thin: they parse CLI args, build a `DeckSettings`/
`GlobalSettings`, and delegate to `src/deckz/pipelines.py`,
`src/deckz/checking.py`, or an `analyzing/*` module — no business logic
lives in the `cli/` layer.

The reverse holds too: the core never draws on the terminal. Rich widgets
live only in `cli/_presentation.py` (`RichTreeVisitor`, `RichProgress`,
`open_path`). The core reports progress through a
`ProgressReporterProtocol` (`NullProgress` by default, `RichProgress` passed
in by the `run` commands) and reports failures by raising a `DeckzError`
subclass, e.g. `DeckParsingError` carrying the deck whose tree `main()`
renders, or `CompilationError` from a failed build. `main()` is the single
error boundary: its cyclopts meta app (`_launch`) takes the global
`--quiet`/`--verbose`/`--debug` flags, sets the log level, and turns any
`DeckzError` into a logged message and exit code 1, without a traceback
(`--debug` or `DECKZ_DEBUG=1` re-raises instead); a usage error exits 2.
On Ctrl-C it exits 130 after `compiler.stop()`, which kills every Typst
worker and refuses new compilations (the deck builder also cancels its
queued ones). Workers start with SIGINT blocked (`_sigint_blocked`), so the
Ctrl-C a terminal sends the whole process group leaves them to the parent.
Logs and progress bars go to stderr, stdout carries only results
(`--json` output included).
Tests driving `main(...)` therefore assert `raises(SystemExit)` with code
1, not the `DeckzError` itself.

`main()` also loads the closest `.env` (python-dotenv), then the user's
(`<user config dir>/.env`, for what every checkout shares), before parsing, so
option defaults can come from environment variables: the shared `Langs`
option (`cli/_options.py`, `--lang fr en`) reads `DECKZ_LANG` on the
commands that process several languages in one pass, and the `run`
sub-app's `Env("DECKZ_RUN_", command=False)` config gives every `run`
subcommand's options a `DECKZ_RUN_<OPTION>` default (one name for all of
them, so `deckz run` and `deckz run deck` agree). Commands showing a
single resolved view take a plain `lang: Lang` instead. Tests clear
`DECKZ_*`, stub out the `.env` lookup and point `XDG_CONFIG_HOME` at an
empty directory (`tests/conftest.py`).

### Settings resolution

`configuring/settings.py` defines `GlobalPaths`/`DeckSettings`/`GlobalSettings`
(Pydantic models). Paths are built from a small template-like mechanism:
fields declared as raw strings like `"{git_dir}/content"` are resolved against
already-computed sibling fields via a custom `BeforeValidator`
(`_convert`/`_Path`). `deckz.yml` and `variables.yml` are looked up and
merged from three locations, in order: the target repo's git root, the
user's XDG config dir, and the current directory up to the git root (see
`utils.dirs_hierarchy` / `load_all_yamls`). `GlobalSettings` covers
repo-wide operations (e.g. `run decks`, asset building); `DeckSettings`
extends it for operations scoped to a single deck (the current working
directory must be inside a deck).

### Components + factories (dependency injection)

`components/protocols.py` defines `Protocol` classes for every major piece
(`ParserProtocol`, `DeckBuilderProtocol`, `CompilerProtocol`,
`RendererProtocol`, `AssetsBuilderProtocol`, etc.), and
`components/factory.py` provides `GlobalSettingsFactory` /
`DeckSettingsFactory` as the construction points — they lazily import and
instantiate the concrete implementation (`components/parser.py`,
`components/deck_builder.py`, `components/compiler.py`,
`components/renderer.py`, etc.) wired up with
paths/settings. Call sites depend on the protocol/factory, not on concrete
classes directly, so new implementations only need to be plugged in at the
factory. That includes `Parser`: a deck's parser comes from
`DeckSettingsFactory(settings, lang=..., lenient=...).parser()`, and one
resolving against shared content only (a lone section, `run shared`/`run
all`) from `GlobalSettingsFactory.shared_parser()`.
`GlobalSettingsFactory.compiler()` returns `TypstCompiler`
(`components/compiler.py`: the `typst` bindings in a child process per PDF,
kept warm across `--watch` rebuilds so Typst's incremental cache survives;
see the module's header comment for why never in deckz's own process;
A deck's Typst fragments go through `FrameMarkingConverter`
(`components/frame_markers.py`): an invisible `<deckz-frame>` marker after
each `# Title`, recording the fragment, the heading's index and its page,
which each compilation queries (before compiling: see `_frames` for why) and
records next to its PDF (`<main>.frames.json`), so that `deckz show frames`
(`analyzing/frames.py`) maps pages to content files and lines at once.
`typst_memory_max` makes it stop a worker whose resident memory, read from
`/proc` every half second, goes over the limit; `typst_machine_compilations`
makes each compilation hold one of a few `flock`ed slot files shared by every
deckz process, `components/machine_slots.py`).

### Build pipeline

`pipelines.py` holds the orchestration the CLI commands call. Planning is
separate from execution: each `run` command first computes its
`BuildTarget`s (`deck_targets`, `file_targets`, `section_targets`,
`decks_targets`, `shared_targets`, `all_targets`: one parsed deck per
requested language, plus the language, settings, failure label and
optional `basedirs` to build each with), then
either `build`s them or, under `--dry-run`, prints their `plan`. The
`run`/`run_file`/…/`run_all` functions are `build` over those targets, kept
for `watch()` to re-run (reparsing on each change). `build` builds the
assets once, then for each target: resolve variables →
cascade them through the parsed `Deck` (`configuring/variables.py::resolve_variables`:
deck-wide `variables.yml`, overridden by each section's own matched-flavor
`variables`, deepest section wins, returning a new `ResolvedDeck` whose
every `File` carries its effective `variables`) → build assets via the assets builder (the
target repo's own `templates/assets_builders.py`, e.g. generated plots) → build the deck
(render Jinja2 → convert Markdown to Typst with pandoc → compile with Typst) via
the deck builder; a target's `basedirs` override is set only by
`shared_targets`/`all_targets` since their synthetic decks can include
files living under any deck's directory, not just one
`current_dir`/`content_dir` pair. `build` raises `CompilationError`, naming
the target's label, when any PDF fails to compile, so every `run` command
fails. A Jinja error in a content file is a `RenderError` naming the file
and line (`render_dependencies`), whose build copy is removed so that the
next build renders it again rather than keep its previous output. Only after every target compiled, `OutputKinds.sync` (`--sync`, on by
default) removes the `stale_pdfs`: the PDFs of the targets' output
directories, in the languages built (`models.lang_dir`), that no build of
the whole deck with every PDF kind would write (a `BuildTarget` keeps its
deck whole and applies `--parts` in `_deck_builder`, for this). What a
narrower build skips is never removed.

Each compilation has an output `Format` (`components/deck_builder.py`):
`CompileType`s `Handout`/`Presentation`/`PrintHandout` are `Typst`, and
`Html` (`--html`, one whole-deck `{deck}-html` item) is `Html`. The factory
hands the deck builder one `OutputFormat` per format (main template,
fragment suffix, Markdown converter, "compiler", output dir): Typst is
`main.typ` + `pandoc_command` + `TypstCompiler` → `pdf/`, HTML is
`main.html` + `html_pandoc_command` + `HtmlPackager`
(`components/html_packager.py`) → `html/<name>/`, a directory synced by
`deck_builder.publish`/`utils.sync_tree`. The main template is rendered
*after* its fragments and gets a `fragment(section)` callable returning a
converted fragment's text: HTML has no `#include`, so `main.html` inlines
them (in Python, never via Jinja `include`, which would re-template `{{`
inside converted code). The packager copies the page as `index.html` plus
every local file it references (attributes, `style`, CSS `url()`/`@import`,
recursively) and the `html_static_dirs`, failing on a missing,
root-absolute or out-of-tree reference. deckz knows nothing of reveal.js:
that, and `FORMAT`-aware Lua filters, are the target repo's business.
`deckz run file`/`deckz run section` get their `.run/` scratch output dirs
from `checking.preview_settings`, a copy of the deck's settings; settings
objects are never mutated after construction. `pipelines.plan` (backing
`--dry-run`) stops before building anything, assets included: it returns
each target's deck builder's `plan()`, a `PlannedCompile` per PDF with the
fragments that would be re-rendered, whose freshness test
(`utils.file_changed` on each `build_copy_path`) is the one `build_deck`
applies. `watch()` is a generic file-watch-and-rerun
wrapper, not build-specific: each of `run/deck.py`, `run/file.py`,
`run/section.py`, and `run/assets.py` calls it directly when invoked with
`--watch`, wrapping that same module's one-shot pipeline call instead of
running it once.

Because a section's resolved `variables` can differ by which flavor
included it, the same physical file can need two different renders within
one build (e.g. two flavors of the same section, each setting a different
value, both pulled into one deck): `components/deck_builder.py` dedupes
build-time dependencies by `DependencyRef` (resolved path + a short hash of
its effective `variables`, from `variables_fingerprint`), not by path alone,
and `dependency_relative_path` is the single place that naming scheme is
decided so the main template's reference (`#include`) and the
on-disk rendered copy always agree.

`shared_targets`/`all_targets` (backing `deckz run shared`/`deckz run all`)
build their `Deck` purely in memory via `src/deckz/checking.py` — no yaml is
ever written to disk. They use `Parser.all_files_section()`
(`components/parser.py`) to expand a shared section to every file in its
own directory rather than a named flavor's `includes` list; `all_targets`
additionally builds one extra copy of a section per deck that locally
overrides one of its files (detected by re-resolving with that deck's own
`local_content_dir`). Both write their output to a persistent
`<git_dir>/.run/{shared,all}/` scratch directory (`checking.run_scratch_dir`),
alongside `deckz run file`/`deckz run section`'s own `<git_dir>/.run/{file,section}/`
scratch trees, since none of these synthetic/preview decks have a real deck
directory of their own. `deckz check variables` uses the same
`checking.check_scratch_dir` helper for its own scratch tree, kept separately
under `<git_dir>/.check/variables/` since it's a `check` command, not a `run` one.
`deckz clean all` sweeps both `.run/` and `.check/` wholesale.

### Hooks

The target repo's `templates/jinja2/env.py` (`environment_for`) and
`templates/assets_builders.py` (`assets_builders`) are loaded through
`components/hooks.py::load_hook`, which turns an import failure, a missing
function or a `DECKZ_HOOKS_VERSION` other than `HOOKS_VERSION` into a
`HookError`; `Renderer`/`AssetsBuilder` also check what the hooks return.
Its module docstring documents the trust boundary (the hooks are arbitrary
code from the target repo).

### Scaffolding

`scaffolding.py` backs `deckz new deck|section` (`cli/new/`) and `deckz labs
new`: the files a new deck, shared section or lab notebook pair needs, in
both languages, from the repository's `templates/scaffold/` when present,
refusing (`ScaffoldRefusedError`) to overwrite anything.

### Status

`status.py` backs `deckz status`: one `StatusSection` per concern (checks,
translation, labs, videos, built decks), each a summary line plus
`StatusItem`s carrying their fix. "Your changes" come from `git status`
and the commits since the upstream's merge base (`base_revision`). It
never touches the network unless `fetch`. `analyzing/affected.py` maps
changed files to the decks resolving them (French; an `en/` file counts
as its French sibling), for `status` and `deckz show affected`.

### Setting up

`setting_up.py` backs `deckz setup`: each step (executables, git hooks,
Claude hooks, `deckz.yml`'s `setup.steps`, videos never rendered) returns a
`SetupItem` (`ok`, `done`, `missing`, `failed`, with how to fix it) and is
idempotent; `check=True` changes nothing. The CLI prints them
(`_presentation.print_setup`) and exits 1 while one is missing or failed.

### Checking

`analyzing/content_checks.py` holds deckz's own generic content checks
(`lab-ids`, `lab-pairs`, `lab-outputs`, `lab-secrets` (with `labs/secrets.py`,
also behind `labs publish`'s refusal), `lab-format`, `asset-credits`,
`raw-latex`, `lab-urls`), each a
`(settings) -> list[str]` function in its `CHECKS` dict.
`components/checks.py::ChecksRunner` merges those with the target repo's
own, from an optional `templates/checks.py` module (`checks(settings) ->
Mapping[str, Callable[[], list[str]]]`, loaded through
`components/hooks.py::load_hook` like every other hook) — a name collision
with a built-in is a `HookError`. `GlobalSettingsFactory.checks_runner()`
is the construction point. `cli/check/content.py` is both `deckz check
content` and (`@app.default`) `deckz check`: with `--staged`, it first
exports the git index's staged tree to `<git_dir>/.check/staged/`
(`checking.py::export_staged`, shelling out to `git ls-files`/
`checkout-index`, no `.git` of its own) and runs the checks against that
instead of the working tree, so another session's unfinished edits neither
block nor hide a check.

`hooks_install.py` writes deckz's own `pre-commit` (`deckz check --staged`)
and `commit-msg` git hooks into the repo's hooks directory (`core.hooksPath`
if set, else `<git_dir>/.git/hooks/`), each a thin shell script shelling
back out to `deckz` (from the `PATH`, else `uv run --quiet deckz`:
`deckz_command`, also used for the Claude Code hooks' commands); refuses to
overwrite a hook file without deckz's own marker line unless `--force`
(`HookInstallRefusedError`). `deckz.yml`'s `checks.opt_in` lists checks that
`deckz check`, the pre-commit hook and the post-edit Claude Code hook skip
unless named (slow, networked, or not yet passing ones).
`deckz hooks install --ci` writes a GitHub Actions workflow
(`hooks_install.ci_workflow`, from `deckz.yml`'s `ci` settings) running the
same checks on every push and pull request, the trailer rule through
`deckz hooks check-commits` (`i18n_stale.one_sided_commits`) on the commits
themselves.
The commit-msg hook (`deckz hooks check-commit-msg`, `cli/hooks/`) reuses
`analyzing/i18n_stale.py`'s fr/en pairing (`content_pairs`/
`notebook_pairs`/`lang_sync_kind`) to refuse, via `CommitRefusedError`, a
commit whose staged diff touches one side of a pair (`staged_one_sided_pairs`)
without a `Lang-sync` trailer in the draft message.

### Data model

`models.py` defines the deck domain model: `DeckDefinition`/`Deck`,
`PartDefinition`/`Part`, section/flavor includes, and the
`ResolvedPath`/`UnresolvedPath` distinction used when resolving shared vs.
local content file/section references. `Parser` (`components/parser.py`)
turns YAML deck/section definitions into this model; the rest of the
pipeline operates on the model, not on YAML directly. The `Deck` tree
(`Deck`/`Part`/`Section`/`File`) is frozen, with tuples of nodes: every
transformation (`Deck.filter`, `resolve_variables`, the synthetic decks of
`checking.py`) builds a new tree with `dataclasses.replace`.

A `SectionDefinition` can declare `variables_to_define` (names every flavor
below it must itself set in its own `variables`, optionally restricted to a
fixed `allowed_values` list) -- a contract, not a default: `Parser` sets a
`parsing_error` if a matched flavor is missing one or sets one out of range.
A `Section`'s `variables` is always just its flavor's own declared delta. A
`File`'s `variables` is empty in a parsed `Deck` and holds the fully
cascaded dict in the `ResolvedDeck` (a `NewType` over `Deck`) returned by
`resolve_variables` (see "Build pipeline" above); the deck builder and
`utils.all_decks` take/return a `ResolvedDeck`, so the type checker
catches an unresolved deck reaching them.

### Analyzing

`analyzing/` holds repository-wide, read-only analyses that don't fit the
build pipeline: flavor renaming/merging, section search, i18n
(fr/en) consistency checks, variable-usage checks, and the generic content
checks (see "Checking" below). These back the
`deckz deps`, `deckz search-sections`, `deckz section-flavors`,
`deckz section-files`, `deckz flavor rename`, `deckz flavor deduplicate`,
`deckz i18n *`, `deckz check variables`, and `deckz check content`
commands.

`variables_usage.py` (backing `deckz check variables`) surveys every shared
section's every named flavor -- via `Parser.from_section`, not the
synthetic "all files" flavor `checking.py` uses, since that one bypasses
real flavors' `variables` entirely -- plus every real deck's own tree, and
reports a fragment reading a `variables.xxx`/`variables['xxx']` name that
isn't resolved at that point (`undefined`), a `variables_to_define` name
nothing under its section ever reads (`unused`), a fragment that fails to
parse with the target repo's own Jinja environment (`unparsable`), and a
flavor/deck that fails to parse at all, typically a `variables_to_define`
contract violation (`structural`, caught per-context so one bad flavor
doesn't abort the whole survey).

### Extras

`src/deckz/extras/` holds the business logic for `deckz extras`'s
subcommands (`github_querying.py` for `issue`, `mailing.py` for `random`)
plus `uploading.py` for the top-level `deckz upload`
— side commands unrelated to the build pipeline, each with its own thin
`cli/extras/*.py` (or `cli/upload.py`) wrapper, same split as everywhere
else in `cli/`. Their third-party clients (Google, GitHub, SendGrid,
email-validator) are the `deckz[extras]` optional dependencies, installed
by the `dev` group: the CLI wrappers import them inside
`extras.extras_imports()`, which turns a missing one into a
`MissingExtraError`. `deckz labs` is unrelated and not under `extras/`: its
library (`src/deckz/labs/`) is plain deckz code with no optional
dependency, backing the top-level `labs` sub-app (`cli/labs/`).

### studioz

`studioz/` is a second package, studioz: a local web UI to work on a
deckz-managed repository (workspaces, previews, editing, commit and sync, and later
agents), on each person's machine. `studioz-plan.md` is its plan, with what is done.
The repository is a uv workspace for it (`[tool.uv.workspace]`, a deliberate
divergence from the Copier template): one `uv.lock`, studioz depends on deckz through
`{ workspace = true }`, pinned to the same version, and the `dev` group installs it
for the tests. deckz's core never imports studioz nor its web stack; studioz uses
deckz's Python API (`deckz.worktrees`, `deckz.setting_up`…), and a rule it needs goes
into deckz, never into studioz.

`studioz.app` holds the FastAPI routes (server-rendered Jinja pages in French,
`templates/`, with htmx), `studioz.workspaces` what the pages show of `deckz
worktree`'s worktrees (studioz's own state goes in each workspace's
`.run/studioz/`), and `studioz.local_only` refuses requests not naming a local host,
and changes not coming from studioz's own pages (DNS rebinding, cross-site
requests): every route that changes something is a POST.
`studioz.watches` runs one `deckz run --watch` per workspace (the workspace's
own deckz, every option spelled out) for the deck page in front of the person,
and reads its state from the log (`deckz.pipelines.watch`'s messages: keep them
in step); the page follows it through server-sent events and shows the
handout in pdf.js, and the watch stops once no page has followed it for 30 s.
Its tests are in `studioz/tests/`, driving the app with FastAPI's test client
on a temporary repository, and the watches with a fake `deckz` printing the
same log lines.

## Conventions

- ruff config selects an explicit rule set (see `[tool.ruff.lint]` in
  `pyproject.toml`) with `preview = true`; docstrings follow Google
  convention and undocumented-code rules (`D1`) are ignored.
- Type checking is done with `ty` (not mypy), scoped to `src/deckz tests` and
  `studioz/src studioz/tests`.

## Operability guidelines

deckz is how people run a deckz-managed repository, with or without an AI
agent: a contributor who never uses one must be able to do every routine
task from `deckz --help` and the docs (`operability-plan.md` holds the
work in progress). Keep new tooling in line with that:

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
