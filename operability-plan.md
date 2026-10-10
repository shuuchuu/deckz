# Operability plan: a deckz repo a human can run without an agent

## Why

shuuchuu/slides has grown a lot of automation, but more and more of what keeps it
correct lives in Claude Code: skills (`.claude/skills/`), Claude hooks, and rules kept
only in one person's private agent memory. A contributor who doesn't use agents gets
neither the procedures nor most of the enforcement. They have the git hooks, and only if
they ran `doit install_hooks`. There is no CI on slides.

deckz was meant to be the tool that operates the repo, so the fix belongs here: task-level
commands with safe defaults, failures that say how to fix them, and a manual written for
people. Agents then use the same commands, and the skills keep only what needs judgment.

## Principles

They're kept for good, beyond this plan, as "Operability guidelines" in `CLAUDE.md`
(and "Tooling and knowledge guidelines" in slides' `CLAUDE.md`). In short:

- **deckz stays generic.** Anything specific to slides (reveal.js vendoring, poppler,
  Manim, its own conventions) is declared in `deckz.yml` or provided by a `templates/`
  plugin, like `checks.py` and `hooks.py` already are.
- **The safe thing is the default.** No option should quietly destroy work, and no
  setting from `.env` should change a result without saying so.
- **Every failure says what to do next**: the command to run, or the edit to make.
- **Humans and agents run the same commands.** A skill that needs three deckz calls in a
  row is a sign a task-level command is missing.
- **Each phase is its own release**, with tests, and slides adopts it right after.

## Phase 1: make `deckz run` safe by default

**Status (2026-10-10):** done and merged (f07f90b, 8a91bb0); slides follows it in
672e3a48 (`typst_memory_max: 5GiB`, CLAUDE.md and qa-fix without the `--sync` and
`systemd-run` warnings). Later phases are tried on slides the same way first: `uv run --with-editable
../deckz-operability` takes precedence over slides' editable `../deckz`. `deckz upload` refuses outdated PDFs
(see the end).

### 1.1 `--sync` removes orphans, not what this run didn't build

Today `pipelines.stale_pdfs` removes every PDF in a deck's output directories that this
run didn't produce, in every language (docstring: "a synced build leaves exactly its own
PDFs"). So a French-only build deletes the English PDFs, a handout-only build deletes the
presentations, and a `--parts` build deletes the other parts. `CLAUDE.md` in slides spends
a paragraph warning about it.

The point of `--sync` is to clean up after a part or deck is renamed or removed. Change
its meaning to match: a PDF is stale when **no build of the current deck definition
would produce it**, whatever kinds, parts or languages this run built.

- `DeckBuilder` gets `expected_output_paths()`: the outputs of every kind and every part
  (handout, part handouts, presentation, print, HTML) for its language, whatever
  `build_*` flags it was given. `output_paths()` stays as it is.
- `stale_pdfs` only looks at the languages this run built (another language's deck may
  not even parse, for example an English file missing), and removes the PDFs there that
  aren't in `expected_output_paths()`.
- Keep the rule that leaves an HTML-only build's PDF directories alone.
- Tests: a fr-only build keeps `pdf/en/`; a handout-only build keeps presentations; a
  `--parts` build keeps the other parts; removing a part from `deck.yml` and then
  building (any scope) deletes that part's PDFs in the languages built.
- Then make `sync` default to true (decided 2026-10-10).

### 1.2 Say what is being built, and where the options came from

Before building, every `run` command logs one line (at info level, so `--quiet` hides
it):

```
Building orsys/dlt: fr + en, handout (+ part handouts) -- lang from DECKZ_LANG (.env), print/presentation off from DECKZ_RUN_PRINT/DECKZ_RUN_PRESENTATION (.env)
```

- To track where each value came from, `main()` records which `DECKZ_*` variables `.env`
  set (python-dotenv can return them), and the `run` app compares the options it got
  with their defaults.
- `--dry-run` prints the same line ahead of its plan.

### 1.3 Guard memory on large builds

`run decks`/`shared`/`all` need a memory cap (`systemd-run --user --scope -p
MemoryMax=5G ...`), and only the docs say so. The largest decks take about 2 GB per
Typst worker.

- New `deckz.yml` setting `typst_memory_max` (e.g. `5G`, unset means no limit).
- `TypstCompiler` reads each worker's resident memory from `/proc/<pid>/status` (Linux;
  the colleague is on Ubuntu too, so no `psutil`) while it compiles.
  Past the limit, it kills the worker and raises `CompilationError` naming the PDF and the
  limit, instead of the whole machine swapping.
- slides sets it, and its `CLAUDE.md` drops the `systemd-run` line.

## Phase 2: `deckz setup`

One idempotent command for a fresh clone, and to re-run after pulling. It prints a
checklist: ok, fixed, or missing, with how to install each missing piece.

- **What deckz itself needs**: `pandoc` (version at least what the filters need), git, a
  `deckz.yml`.
- **What the repo declares**, in a new `deckz.yml` section:

  ```yaml
  setup:
    requires:
      - command: pdftocairo
        why: SVG versions of the PDF figures for HTML decks
        install: apt install poppler-utils
      - command: ffmpeg
        why: rendering the Manim videos
        install: apt install ffmpeg
    steps:
      - name: reveal.js and MathJax for HTML decks
        run: [npm, ci, ...]          # what `doit web` runs today
        creates: assets/web/vendor   # skipped when present; --force re-runs
  ```

- **Git hooks**: `install_hooks()`, reporting a non-deckz hook it refuses to overwrite.
  The Claude hooks only with `--claude` (a colleague without agents doesn't need them).
- **Videos**: render the scenes that have no render (`deckz videos render`, at draft
  quality with `--quick`), since a deck using an unrendered video fails.
- `deckz setup --check` only reports, changes nothing, and exits 1 if something is
  missing: the first thing to suggest when a build fails in an odd way.
- slides: `doit web`, `doit install_hooks` and `doit videos` go away, or become aliases of
  `deckz setup`.

## Phase 3: `deckz status`

One command answering "where is my work, and what's left before I can commit, teach or
publish". Each item ends with the command that resolves it. `--json` for agents.

1. **Checks**: `deckz check` on the working tree, problems grouped by file.
2. **Translation**: `i18n stale` limited to the files changed in the working tree and in
   the commits not yet pushed, plus `missing-en` for the decks those files belong to.
   Plus one line with the repository-wide backlog (how many files `stale` lists, the
   oldest one's age): the maintainer's queue of English ports.
3. **Labs**: notebooks without an ID; notebooks whose committed version differs from the
   published one (built on `labs/publishing._published_notebooks`; this is what slides'
   `tools/labs.py links` checks today); demos whose code changed after their outputs
   were last written back (git history, as `i18n stale` does), the one rule about demo
   outputs that no check covers yet.
4. **Videos**: scenes with no render, draft renders, renders not yet published
   (`videos.publishing.unpublished_reason`).
5. **Built decks**: for decks affected by the changes (see below) that have a built
   handout, its shrunk frames (`analyzing/overflow`) and whether the handout is older
   than its sources.

Building blocks:

- `deckz show affected <path>...`: the decks (and shared flavors) whose resolved files
  include a path. Phases 3 and 5 both need it, and it replaces "grep `content/` to
  guess".
- Network access (fetching the `labs`/`videos` remotes) only with `--fetch`. Without it,
  use the last fetched refs and say how old they are.

## Phase 4: scaffolding for the mechanical half of new work

The judgment part (which sections fit a program, what a lab should teach) stays with
people and skills. The file layout shouldn't need either.

- **`deckz labs new <topic>/<lab> <hands-on|demo>`**: creates the fr and en notebooks
  from the repo's templates (`templates/scaffold/lab/<type>.ipynb` when present, else a
  minimal Colab notebook through `normalize`), in canonical format, with IDs from
  `assign_ids`, and prints the `{{ "<topic>/<lab>" | lab("<type>") }}` call to paste.
  Refuses a lab name that breaks the naming rules (kebab-case ASCII; slides' rules for
  frameworks and forbidden words come from a `deckz.yml` pattern).
- **`deckz new deck <dir>`**: `deck.yml`, `variables.yml`, and the deck's local content
  stubs in both languages, from `templates/scaffold/deck/` (Jinja, given the deck name
  and title). Validates that the directory matches the catalog layout.
- **`deckz new section <path>`**: `<name>.yml` with one flavor, a first `.md` and its
  `en/` twin. Runs `search-sections` on the name first and lists close matches, so nobody
  creates a duplicate by accident.

## Phase 5: a deckz that explains itself

### 5.1 Task-oriented help

Group the top-level commands with cyclopts `Group`s: **Everyday** (`run`, `check`,
`status`, `show`), **New content** (`new`, `labs new`, `search-sections`), **Translation**
(`i18n`), **Labs and videos** (`labs`, `videos`), **Repository maintenance** (`flavor`,
`deps`, `asset`, `clean`, `setup`), **Agents and hooks** (`hooks`,
`generate-agent-notes`). `deckz --help` then reads as a menu of tasks instead of a list
of 22 commands.

### 5.2 Every finding says how to fix it

- Extend the check contract (`(settings) -> list[str]`) so a finding can be a
  `Finding(message, fix=None)`. Plain strings stay accepted, so `templates/checks.py`
  plugins keep working.
- Give every built-in check a `fix` (e.g. lab-ids: `deckz labs ids`; lab-pairs: `deckz
  labs compare <dir>`; raw-latex: the Markdown equivalent from the table).
- The commit-msg hook prints, per one-sided file, the trailer to paste
  (`Lang-sync: fr-only (<reason>)`, `Lang-sync: pending`), and says that `pending` is
  fine when the port comes later. The colleague can then commit in French only, and the
  translation catch-up happens separately, from `deckz i18n stale`.

### 5.3 Close the gaps behind the agent-only rules

These rules are enforced today only by what an agent remembers (reviewed in slides on
2026-10-10):

- **`--no-verify`**: add `git commit --no-verify`/`-n` and `git push --no-verify` to the
  built-in Bash denials. It's the one flag that skips every git hook. CI (phase 6) covers
  humans.
- **Secrets in lab notebooks** (the labs repo is public): a built-in `lab-secrets` check
  for token patterns (GitHub, Hugging Face, OpenAI/Anthropic, AWS, DagsHub, generic
  `api_key = "..."` assignments) in sources and stored outputs. It runs in the pre-commit
  hook, and `labs publish` refuses to publish on a hit.
- **Canonical notebook format**: a `lab-format` check comparing each notebook with what
  `fmt` would write.
- **Outputs post-processing**: `deckz labs outputs` runs a hook the repo declares in
  `deckz.yml` (`labs.outputs.hooks`, like `labs.gpu.hooks`) on the notebook it wrote.
  slides uses it for the Evidently demos, whose reports must load their JavaScript
  from jsDelivr instead of inlining 3.5 MB per report. Today that step is only in a
  memory note.

## Phase 6: CI for the managed repo

`deckz hooks install --ci` writes `.github/workflows/deckz.yml` (marked like the git
hooks, refusing to overwrite a hand-written one):

- It runs in the `shuuchuu/deckz-ci` image (pandoc and friends), with deckz checked out
  next to the repo: slides' `[tool.uv.sources]` points at `../deckz`, so the workflow
  checks out shuuchuu/deckz into `../deckz` (at a tag pinned in `deckz.yml`, or `main`).
- On push and pull request: `deckz check --plain`, plus `deckz hooks check-commit-msg`
  on each new commit (the hooks a contributor may never have installed).
- Nightly: `lint-full`'s equivalent (`deckz check missing-en published-videos`, `deckz
  check variables --lang fr en`), and handout builds of the decks changed that day
  (`deckz show affected`), with `typst_memory_max` set.

## Phase 7: a manual for people

- **deckz docs** (mkdocs; `docs/index.md` currently only links the code reference): a
  "Running a deckz repository" guide, one page per task: setup, the edit loop
  (`run --watch`), adding a slide, a figure or a video, adding or changing a lab,
  translating (`i18n missing-en`/`stale`, trailers), checking a deck before teaching it
  (`status`, `check overflow`, `check parity`), publishing labs and videos, and what
  each check means, with its fix. README.md keeps the configuration reference and
  links to the guide.
- `generate-agent-notes` points agents at the same guide instead of repeating it.

## Then, in slides

Once each phase has shipped:

- `README.md` points to a short `HANDBOOK.md`, in French: the repo's own conventions and the deckz
  guide pages to follow, nothing that duplicates `deckz --help`.
- Move the rules now kept only in private agent memory into the repo: phase 7b of
  slides' `reorganization-plan.md` maps each memory file to its destination (a new
  `docs/conventions.md`, `labs/README.md`, notebook cells, docstrings).
- `CLAUDE.md` gets an "Agents only" section for what exists only because several agent
  sessions share one checkout (staging your own hunks, the denials). The rest of it
  points to the handbook.
- The skills call the new commands (`status`, `labs new`, `new deck`/`section`, `setup`)
  and keep only orchestration and judgment: QA criteria, translation fidelity,
  subagents, questions for the user.
- Delete the doit tasks that `deckz setup` replaces, and the `systemd-run` and `--sync`
  warnings.
- **Acceptance test**: the colleague does three real tasks with only the handbook and
  `deckz --help` (fix a slide in both languages, add a lab, get a deck ready to teach on
  Monday), and we note every place they got stuck.

## Decisions (2026-10-10)

1. **`--sync` becomes the default** once it only removes orphans (1.1).
2. **Platform: Ubuntu**, like the maintainer. Linux-only mechanisms (`/proc` in 1.3) are
   fine, and `deckz setup`'s install hints are `apt` commands.
3. **Language:** slides' human docs (the handbook, `docs/conventions.md`) are in French.
   deckz's own guide stays in English, as a generic tool's docs.
4. **`deckz status` scope:** the working tree plus the commits since the merge base with
   the upstream branch (`origin/main` today). slides commits straight to `main`, so
   that's "not pushed yet". It keeps working unchanged if slides moves to branches and
   pull requests. `--since <rev>` widens it, e.g. to review a week of work.
5. **Translation catch-up:** the maintainer ports the English side. A French-only
   commit from the colleague carries `Lang-sync: pending` (5.2 makes the hook offer it),
   and `deckz status` lists what's pending, so no scheduled agent is needed.

## Resolved: `deckz upload` and skipped PDFs

Since `--sync` keeps what a build skips, a deck's `pdf/` can hold PDFs built long ago.
`deckz upload` now refuses when a PDF doesn't match the deck's content
(`pipelines.outdated_pdfs`: a fragment changed since it was built, the Markdown
conversion changed, or no build produces it), before signing in; `--include-stale`
overrides. Skipping them instead would have deleted their remote copies, and the links
already shared. `deckz status` (phase 3, item 5) reuses `outdated_pdfs`.
