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

**Status (2026-10-10):** done and merged. Built as planned,
except that videos are only reported unless `--videos` (a render at the published
quality takes minutes per video). Slides follows in 53f81102: `setup.requires`
(pdftocairo, npm, ffmpeg, xelatex, dvisvgm, with Ubuntu packages and the Fira fonts the
videos need) and a `setup.steps` entry running `uv run doit web`; doit `install_hooks`
is gone.

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

**Status (2026-10-10):** done and merged, except two items:
`missing-en` for the decks your changes reach (slow, about a minute for every deck; CI
can run it), and demos whose code changed after their outputs were written. The checks
run on the working tree (about 15 s on slides; `--no-checks` skips them). The
translation backlog line is there for the maintainer.

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

**Status (2026-10-10):** done and merged. Differences: the
lab name rule is deckz's generic one (kebab-case path parts), not slides' framework and
forbidden-word rules, which belong in a slides check; `labs.link_snippet` prints the
repository's own link syntax; `new deck` doesn't check the catalog layout (a slides
convention). Slides follows in 53f81102: `templates/scaffold/deck/` (`deck.yml.jinja`,
whose `$about@CHOISIR` fails the build until a flavor is picked, `variables.yml.jinja`,
`content/about/description.md` and its `en/`), and `labs.link_snippet`. A template's
YAML files take a `.jinja` suffix, which `new deck` drops: deckz found a template's
`deck.yml` as a deck (94f799c).

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

**Status (2026-10-10):** 5.1, 5.2 (the check messages and the commit-msg hint, without a
structured `Finding` type yet: `deckz status` will need one) and 5.3 done and merged.
Groups as planned, except that `upload` is under Everyday
and `generate-completion` under Setting up; there is no `new` group until phase 4.
`lab-secrets` and `lab-format` find nothing on slides and take about 2 s each, so they
needn't be opt-in there.

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

**Status (2026-10-10):** done and merged, never run on GitHub
(that needs a push). Adds `ci.apt_packages`: slides' `uv sync` builds pycairo (manim),
which needs `libcairo2-dev` and `pkg-config` (and likely `libpango1.0-dev`), and
downloads tensorflow, so its first runs will need adjusting. Builds of changed decks
aren't in it: they need the assets toolchain (pdftocairo, xelatex, renders), a later
step. The commit-msg rule runs on the commits themselves (`deckz hooks
check-commits`), not on a message file.

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

**Status (2026-10-10):** the deckz guide is written (`docs/guide/`, eight pages, in the
mkdocs site; `mkdocs build --strict` passes), merged. The
agent notes point agents to it. Slides' French handbook comes after the merge, since
it documents these commands.

- **deckz docs** (mkdocs; `docs/index.md` currently only links the code reference): a
  "Running a deckz repository" guide, one page per task: setup, the edit loop
  (`run --watch`), adding a slide, a figure or a video, adding or changing a lab,
  translating (`i18n missing-en`/`stale`, trailers), checking a deck before teaching it
  (`status`, `check overflow`, `check parity`), publishing labs and videos, and what
  each check means, with its fix. README.md keeps the configuration reference and
  links to the guide.
- `generate-agent-notes` points agents at the same guide instead of repeating it.

## Then, in slides

**Status (2026-10-10):** slides 53f81102 has `HANDBOOK.md` (French), the README
pointer, the CI workflow (its steps pass in the `shuuchuu/deckz-ci` image; deckz
4c20039 and 7b27baf fixed the template on the way), `nouvelle-formation`/
`nouvelle-section` calling `new deck`/`new section`/`labs new`, and `install_hooks`
gone. Slides 71de77d0 then moved the memory-only rules into the repo (reorganization
plan phase 7b: `docs/conventions.md`, `docs/decisions.md`, `labs/README.md`, docstrings),
added `CLAUDE.md`'s "Agents only" section and pointed the skills at the docs and at
`deckz status`; the `labs gpu` lessons went to this guide (f08ef47). Left: the
acceptance test, and automating the Evidently outputs rewrite (`labs.outputs.hooks`,
5.2, still a manual step in slides' `labs/README.md`).

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

## Phase 8: commit freely, settle later

**Status (2026-10-18):** planned, discussed with the maintainer today.

The colleague should be able to use the repository naively, `git commit` without
choosing a `Lang-sync` trailer or fixing every check, and have it work. What was left
undone stays visible to the tooling, and the maintainer settles it when it's due.
Today two hooks refuse such a commit: commit-msg wants a `Lang-sync` trailer on a
one-sided change, and pre-commit's `deckz check --staged` fails on any finding.

The two kinds of debt are tracked differently:

- **Translation is a fact about history**: the tree can't show that French changed
  after English. It's marked in the commit, and already is: `i18n_stale` reads a
  commit with no trailer as `Lang-sync: pending`, so the refusal protects nothing, it
  only makes the colleague write a choice that doesn't change the result.
- **A check's finding is a fact about the tree**: `deckz check` on `main` shows what's
  broken now, whichever commit did it. Marking commits "to revisit" would be redundant,
  and wrong after a hook was skipped, a later fix, or a rebase. It's recomputed
  (`deckz status`, studioz's Problèmes tab), and settled by a fixing commit.

### 8.1 The commit-msg hook marks instead of refusing

**Status (2026-10-18):** done. `i18n_stale.mark_pending` appends the trailer
through `git interpret-trailers` (above git's comments and `commit -v`'s scissors,
which the hook's file still holds) and the hook lists the files, `deckz i18n stale`
and `mark-synced`. The hook still refuses, and `check-commits` fails on, one case:
a `Lang-sync` line that isn't read (`unread_lang_sync`: `fr only (…)`, or not in
the last paragraph), whose choice would be lost silently. `check-commits` lists the
commits left pending without failing. studioz's Commit dialog checks "La
traduction suivra" by default. Tried on a scratch worktree of slides: a plain
`-m` commit marked (1.6 s), `fr-only` kept through an editor commit with `-v`, a
misspelled line refused; `check-commits` over slides' 1,405 commits passes, listing
18 pending, so no old commit turns CI red. The CI workflow is unchanged.

- A one-sided change without a trailer gets `Lang-sync: pending` appended to the
  message by the hook itself (a commit-msg hook may edit the message file), and the
  hook prints the files left to translate and `deckz i18n stale`. The marker is then
  present, readable in `git log`, rather than inferred from an absence. A commit that
  skipped the hook gets the same result from `i18n_stale`'s reading.
- `fr-only`/`en-only` stay an explicit choice, the only one that exempts a pair. A
  commit that should have carried one is settled later with `deckz i18n mark-synced`.
- `deckz hooks check-commits` in CI no longer fails on a missing trailer (it could
  still check that a trailer present is well-formed).
- studioz's Commit dialog keeps asking, with `pending` as the default answer.

### 8.2 Blocking and deferred checks

**Status (2026-10-18):** done. The open question's answer was no: nothing run at
commit parsed a deck (slides' `deck-files` only checks which files a deck directory
holds). A new built-in, blocking `deck-definitions` parses every deck in French
(`deck.yml`, the sections and flavors it includes, the files they name,
`variables.yml`), in 0.9 s on slides' 43 decks with a pool of 4, once `load_yaml`
used libyaml's loader: PyYAML's pure-Python scanner was 11 s of 14 s profiled (each
deck loads every section it includes again: 1,213 loads), which speeds up every
deck parse in deckz. `checks.deferred` (unset: `content_checks.DEFERRED`, every
built-in but `lab-secrets`, `jinja-syntax`, `deck-definitions`; a list replaces it)
and `ChecksSettings.blocking`. `deckz check` exits 1 on blocking findings only, or on
any finding of a check named on its command line (so CI's nightly `deckz check
missing-en` still fails); `--plain` gains a first `blocking`/`deferred` column and
`--json` the two keys (nothing parsed either). `deckz status` sorts the blocking
findings first, marked, its summary counting them (`StatusItem.blocks_commit`);
studioz badges them "bloque le commit" and the Commit dialog counts them apart. The
post-edit Claude hook still reports every finding of the file edited: an agent
settles debt in what it touches. Tried on a scratch worktree of slides: clean in
19 s (the whole pre-commit run); a staged `{=latex}` block printed, exit 0; a staged
deletion of `ai/history-light.md` refused (`decks/orsys/iao/deck.yml`), exit 1.
Left for 8.4: slides' `deckz.yml` comment and handbook still say the commit-msg hook
refuses.

Not every check can wait: for some, the commit (or the push, since slides commits to
`main`) is the point of harm.

- **Blocking**: `lab-secrets` (a secret stays in the history) and `jinja-syntax` (every
  `git pull` breaks everyone's build, the maintainer's agent sessions included).
- **Deferred**: the rest (`lab-ids`, `lab-pairs`, `lab-format`, `asset-credits`,
  `raw-latex`), with a gate where their harm happens (8.3).
- deckz gives its built-in checks this default; a new `deckz.yml` setting next to
  `checks.opt_in` (e.g. `checks.deferred`, or a level per check) changes it. A plugin
  check from `templates/checks.py` is blocking unless listed, as every check is today.
- `deckz check` (pre-commit, CI on push) fails only on blocking findings, and prints
  the deferred ones with their fix, without failing. A red CI on every push of the
  colleague's would soon be ignored.
- The pre-commit hook keeps checking the whole staged tree, not the diff. That is
  only workable because `main` holds no blocking finding: if deferred findings could
  fail it, the colleague's debt would refuse the maintainer's next, unrelated commit.
  Comparing findings against `HEAD` (a baseline, as linters do) was considered and
  rejected: messages carry line numbers that shift, and the split makes it unneeded.
- To check: whether a deck or section `.yml` that doesn't parse is caught by any check
  run at commit. It breaks the build like a Jinja error.

### 8.3 Gates where the debt is due

**Status (2026-10-19):** done, without changing the check contract: every built-in
problem already starts with its file, as plugins' are asked to, so
`ChecksRunner.findings()` returns `Finding(check, text, blocking)` whose `path` is
that leading path, and each gate filters by it. `deckz upload` refuses while a
problem names a file the deck reaches (`affected.reaches`: under its directory, or
resolved by it, an English file as its French sibling; `deck-definitions` names the
deck's own `deck.yml`), listed with the outdated PDFs in one refusal, and `--dry-run
--json` gains `problems`. `deckz labs publish` refuses while one is under the
notebooks directory (a credential still refused inside `publish`, whatever the
flag). Both take `--skip-checks`. `deckz status DECK` (`status.deck_status`): the
deck's problems, its stale files, its PDFs outdated or missing, and each language's
shrunk frames and wrapping lines from what its build recorded; `--since`/`--fetch`
with it are refused. studioz's Upload dialog keeps its dry run fast
(`--skip-checks`: every check takes ~20 s on slides), says the upload checks the
deck's files, and has "Envoyer malgré les problèmes". Not mapped: `asset-credits`
(which decks show an asset isn't known). Tried on slides: `deckz status
decks/eni/cv3` in 11 s (checks and translation clean, 6 outdated PDFs, shrunk frames
with their sources); on a scratch worktree, a `{=latex}` block in `gan.md` showed in
`cv3`'s upload dry run and not `ml1`'s, and a reformatted notebook was the publish
gate's only finding of the two planted.

"Settled in due time" needs a time. The debt is collected at the points where it would
do harm, which already refuse other things:

- **`deckz upload`** refuses a deck whose files carry a deferred finding, as it refuses
  outdated PDFs, with the same kind of override.
- **`labs publish`** refuses a notebook with a `lab-ids`, `lab-pairs` or `lab-format`
  finding (it already refuses `lab-secrets`).
- **"Ready to teach on Monday"**: `deckz status <deck>`, the debt of one deck's files
  (findings, translation pending for the language taught, shrunk frames, outdated
  handout).

These need the structured finding 5.2 left out: `Finding(path, message, fix)`, so a
finding maps to the decks resolving its file (`analyzing/affected.py`). Plain strings
stay accepted from plugins, mapped by their leading path when there is one.

### 8.4 Docs

**Status (2026-10-19):** done. The guide's pages followed 8.1–8.3 as each shipped.
Slides 7c41b332: `HANDBOOK.md`'s "Traduire", "Committer", "Avant d'enseigner" and
"Publier" (commit as you like; what blocks a commit and why; `deckz status <deck>`,
`upload` and `labs publish` where the rest is due), `CLAUDE.md`, the `qa-fix` and
`sync-langs` skills and `deckz.yml`'s comments no longer describe the refusal. Slides'
house checks all blocked (a plugin check blocks unless listed), so its `deckz.yml`
gains `checks.deferred`: deckz's deferred built-ins, repeated since the list replaces
them, plus `lab-frames`, `lab-hands-on`, `lab-cpu`, `lab-portable`, `lab-typography`,
`lab-ruff`, `deck-files` and `quiz-answers`; `python` (its problems name no file, so
no gate catches them) and `lab-codespace` stay blocking. Tried on a scratch worktree:
a staged wrong quiz answer and a French notebook's missing non-breaking space, all
deferred, exit 0; the commit went through marked `Lang-sync: pending`, and `bdm`'s
upload dry run listed the quiz's two problems. Left: the acceptance test with the
colleague ("Then, in slides").

The guide's translating and checks pages, then slides' `HANDBOOK.md`: commit as you
like; what blocks a commit and why; where the debt shows (`deckz status`, studioz),
and when it must be settled.

### Decisions (2026-10-18)

1. Translation debt is marked in the commit (`Lang-sync: pending`, added by the hook);
   check debt is never marked, only recomputed from the tree.
2. Only `lab-secrets` and `jinja-syntax` block a commit by default; the other built-in
   checks are deferred to `upload`, `labs publish` and `deckz status <deck>`.
3. The colleague commits; the maintainer settles the debt (as decision 5 above already
   has it for translation).
