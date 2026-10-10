# studioz plan: a UI for operating a deckz repo, agents included

## Why

The operability plan (`operability-plan.md`) made shuuchuu/slides runnable without an
agent: task-level deckz commands, findings that name their fix, a manual for people.
What still needs an agent is the judgment work: writing a deck from a program, QA and
its fixes, translation, figures, videos, labs. Today that means a Claude Code terminal
session, which takes knowing deckz, the repo's conventions, git, and how to steer an
agent. A colleague who knows the training content but none of that can't do it.

The goal is a local web UI, studioz, where such a person does every routine action of
the repo, with an experience close to a Codespace: they open a workspace, work on the
material itself (decks, sections, figures, labs, videos), seeing it rendered as it
changes, by hand or with an agent (new deck, edit slides, QA then fixes, sync
languages, figures, labs, videos), answer the questions the agent asks, and commit
when *they* decide the work has reached a point worth keeping, then sync. Experts keep
the terminal: theme, filters and deckz work stay out of scope.

## Principles

- **A client of deckz and the skills, never a third source of rules.** Every rule stays
  where the guidelines put it: checks in deckz or `templates/checks.py`, procedures in
  deckz commands, judgment in skills, conventions in the docs. studioz only calls
  them and shows what they return. If the UI needs a rule, that rule is missing from
  deckz.
- **Deterministic actions don't go through the agent.** Building, checking, status,
  uploading and publishing are deckz commands, run directly: instant, free, and usable
  without an agent at all.
- **Work happens in workspaces**: long-lived git worktrees, one per line of work,
  never the shared checkout (see slides' `CLAUDE.md`, "Shared checkout"). studioz
  doesn't write to the main checkout at all: it only hosts the environment and the git
  object store.
- **The person commits, never the agent.** Agent turns and manual edits accumulate in
  the workspace, shown rendered as they happen; a commit is the person's decision,
  made from a view of everything that changed since the last one. Pushing is another,
  separate decision (Sync).
- **Everything is seen before it's kept.** The person judges rendered material (live
  previews, before/after since the last commit) and the checks' verdict, never a
  Markdown or Typst diff, which stays available on demand.
- **No raw tool approvals in front of a non-expert.** The agent runs under rules that
  make "Allow `uv run deckz run ...`?" prompts unnecessary. The only questions shown are
  the ones a skill asks on purpose (`AskUserQuestion`), and publishing.
- **Generic, like deckz.** studioz knows deckz, not slides: the workflows it offers
  are declared by the repository (`deckz.yml`), and the skills they run are the
  repository's.

## What already exists

| Need | Already there |
|---|---|
| Dashboard data | `deckz status --json` (checks, translation backlog, unpublished labs/videos, outdated PDFs, each with its fix) |
| Per-deck views | `deckz show paths`, `deckz show affected`, `deckz i18n missing-en`, `deckz check overflow`, `deckz deps` |
| Scaffolding | `deckz new deck`/`new section`, `deckz labs new` |
| Previews | `deckz run --watch` (0.5 s rebuilds measured), `deckz run file`/`run section` (one file or flavor under `.run/`), `--html` (reveal.js page, embeddable; 5.2 s for `orsys/pnd`) |
| Guardrails independent of the client | git hooks (`deckz check --staged`, `Lang-sync` trailers), Claude Code hooks in `.claude/settings.json` (Bash denials, post-edit checks, Stop parity check), CI |
| Judgment workflows | slides' skills: `nouvelle-formation`, `nouvelle-section`, `qa-formation`, `qa-fix`, `sync-langs`, `markdown-edge-cases`, plus `explain-figure`, `manim-lesson` |

## Running agents: the Claude Agent SDK

Not bare `claude -p`: the Python Agent SDK (`claude-agent-sdk`) is the same harness as a
library, and it provides what the UI needs (checked against its documentation on
2026-10-10):

- **Questions.** A skill's `AskUserQuestion` reaches the `can_use_tool` callback with
  its `questions` (text, header, 2-4 options, `multiSelect`); the UI shows them as a
  form and answers with `PermissionResultAllow(updated_input={"questions": ...,
  "answers": {question: label}})`. The callback may stay pending indefinitely; for a
  person who answers hours later, a `PreToolUse` hook can return `defer` instead, so the
  process exits and the conversation resumes from the saved session. Limitation:
  `AskUserQuestion` isn't available in subagents. slides' skills already ask from the
  main agent (`qa-fix` asks before launching its workers).
  The Python SDK needs streaming input plus a no-op `PreToolUse` hook for
  `can_use_tool` to work: the documented workaround.
- **Project settings.** Omitting `setting_sources` loads user, project and local
  settings, so the agent would also get the user's own `~/.claude` setup and auto
  memory. studioz passes `setting_sources=["project"]` (CLAUDE.md, skills, the
  project's hooks), `cwd=<worktree root>` (project hooks load from `<cwd>/.claude/`
  only), and `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`: what a session learns goes into the repo
  or the workspace's record, per the guidelines.
- **Sessions.** `ResultMessage.session_id`, then `resume=` (and `fork_session=`) to
  continue a task after a follow-up instruction, a crash or a deferred question.
- **Usage.** `ResultMessage.total_cost_usd` and `model_usage` per run (an API-price
  estimate; on a subscription it measures how much of the plan's limits a task used,
  not a bill); `max_budget_usd` caps one.
- **Permissions.** `permission_mode`, `env`, `add_dirs`, `sandbox` (see Phase 3).

### Credentials: each person's own Claude subscription

The SDK runs the unmodified Claude Code binary, which authenticates the way the
`claude` CLI on that machine is logged in. With no `ANTHROPIC_API_KEY` in its
environment, that's the person's own Claude subscription (Pro or more). Anthropic's
terms (code.claude.com/docs/en/legal-and-compliance, "Authentication and credential
use", read 2026-10-10) draw the line this plan stays on:

- allowed: "an end user signing in to the unmodified Claude Code binary with their own
  Claude subscription", and the plans' limits "assume ordinary, individual usage of
  Claude Code and the Agent SDK";
- not allowed: a third-party application offering Claude.ai login, routing requests
  through Free/Pro/Max credentials on behalf of its users, or collecting, storing or
  intermediating Claude.ai credentials or tokens.

So studioz never handles credentials. It runs on each person's machine, for that
person only. It checks `claude auth status --json` (`loggedIn`, `authMethod`) and, when
nobody is logged in, tells the person to run `claude` and log in through Anthropic's
own flow. It removes `ANTHROPIC_API_KEY` from the agent's environment, so a key left in
a shell can't silently take over billing, and it never uses `claude setup-token`. Each
person uses their own account, never a shared one. A team that wants certainty about
an internal tool built this way can ask Anthropic's sales team, as the terms suggest.

The practical constraint is the plan's usage limits, not money. A QA pass with
subagents on a large deck can use a large share of a Pro plan's window. So studioz
shows each run's usage, and treats a rate-limit stop as a pause: it shows when the
limit resets and resumes the session then. The SDK streams the numbers it needs: each
`RateLimitEvent`'s `rate_limit_info["raw"]["unifiedWindows"]` gives the five-hour and
seven-day windows' utilization and reset times (seen in the spike).

## The worktree question

Every path deckz uses hangs off the repository root, which `get_git_dir` takes from
pygit2's `Repository.workdir`, and which is the worktree's own root in a linked
worktree (`configuring/settings.py`, `GlobalPaths`: `assets_dir`, `content_dir`,
`labs/notebooks`, `.run/`, `figures/scenes`, `templates/`; `DeckPaths`: each deck's
`.build/`, `pdf/`, `html/`). So a worktree is already an isolated repository for deckz, which
makes it the natural workspace: builds, previews, `.run/` and PDFs don't collide with
the main checkout's. Settings
merge `deckz.yml` from the root, the user config dir, then each directory down to the
deck, all inside the worktree. What a fresh worktree lacks is everything git doesn't
track:

| Missing in a fresh worktree | Size (slides, 2026-10-10) | How it's rebuilt | Cost |
|---|---|---|---|
| `assets/typ/` (Typst figures as SVG) | 25 MB | assets build (`TypstFiguresAssetsBuilder`) | minutes |
| `assets/svg/` (SVG copies of PDF figures, HTML decks) | 86 MB | assets build (`SvgAssetsBuilder`, `pdftocairo`) | minutes |
| `assets/web/vendor/` (reveal.js, MathJax) | 11 MB | `setup.steps` (`doit web`, npm) | network, ~1 min |
| `assets/videos/**/*.{mp4,png,quality}` | 100 MB | `deckz videos render` (Manim, 1080p60) | hours |
| `.venv/` | 3.1 GB | `uv sync` | slow; needs a C toolchain for pycairo |
| `.env` (`DECKZ_*` defaults, lab secrets) | — | by hand | — |

`assets/plt` and `assets/pltly` are committed, so they come with the checkout.

### Finding 1: freshness is decided by mtimes, which a checkout resets

Every builder decides staleness by comparing modification times:

- `deckz/videos/scenes.py:196`: a render is stale if older than its scene module.
- `deckz/components/typst_figures_builder.py:104`: a figure's SVG is stale if older
  than the figure or than the newest shared input (`_lib.typ`, `_plot.typ`, the theme).
- slides' `figures/deckz_asset_builders/__init__.py:134` and `:212`: same for plots and
  SVG copies.

`git worktree add` writes every source file with the current time. Seeded outputs copied
with their times (`cp -a`) are then all older than their sources, so the first build
re-renders every figure and every video. Copied without their times, they all look
fresh, including the ones whose source differs between the main checkout's working
tree (another session's uncommitted figure edit) and the workspace's base commit. The
workspace would then silently show the wrong render.

The fix belongs in deckz and helps people too: **freshness by content hash, not
mtime.** Each output gets a stamp of what it was built from (source bytes, the shared
inputs' bytes, and, for videos, the quality, which the `.quality` stamp already records).
A builder rebuilds when the stamp doesn't match. A seeded copy is then correct by
construction, and in the main checkout too, a branch switch or `git stash` stops
re-rendering everything. For videos, the stamp also fixes the `--force` gap after
editing a module a scene imports, if the stamp covers the repo-local modules it imports
(Manim scenes import `figures/scenes/lesson.py` and the like).

The spike found a worse case of the same thing, which hits every fresh clone today:
**the committed plots.** `assets/plt` and `assets/pltly` are in git, and git checks
`assets/` out before `figures/`, so every plot's `.py` is newer than its PDF. The first
build rebuilt all 101 of them, matplotlib wrote a new `CreationDate` into each, and git
showed 101 modified files: a task's commit, or a colleague's first `git add`, would
carry them. Hash stamps remove the rebuild, and the plot builders must also write
reproducible PDFs (matplotlib's `metadata={"CreationDate": None}`, or
`SOURCE_DATE_EPOCH`), so that a rebuild of an unchanged plot changes no byte.

### Finding 2: the venv and `../deckz`

slides depends on deckz through `[tool.uv.sources] deckz = {path = "../deckz",
editable = true}`. A worktree outside `shuuchuu/` breaks that path, and a per-worktree
`uv sync` costs a 3.1 GB environment (hard-linked from uv's cache, but still slow, and
pycairo needs compiling). Instead, every task uses the main checkout's environment:
`PATH` starts with `<main>/.venv/bin`, so the hooks (`if command -v deckz ...; else uv
run ...`) find `deckz` directly. For the agent's own `uv run deckz ...` calls,
`UV_PROJECT_ENVIRONMENT=<main>/.venv` with `UV_NO_SYNC=1` (verified in the spike: no
`.venv` is created, deckz resolves every path in the worktree). Under the sandbox,
`~/.cache` is read-only, which breaks `uv run` (it takes a lock in its cache) and makes
matplotlib warn, so the workspace's caches live in its gitignored `.run/cache`
(`UV_CACHE_DIR`, `XDG_CACHE_HOME`, `MPLCONFIGDIR`).
Worktrees go next to the repository (`../slides.tasks/<task>` breaks `../deckz`;
`../slides--<task>` doesn't), so that a stray `uv sync` still resolves. A task that
changes `pyproject.toml` or `uv.lock` can't share the environment; studioz refuses
those (expert work).

### Finding 3: no copy-on-write here

The disk is ext4 (no reflinks), so seeding copies about 220 MB per worktree: a few
seconds. Hard links would cost nothing but are unsafe unless every builder replaces
files by renaming rather than rewriting them in place, which nothing guarantees today.
A shared content-addressed cache (`~/.cache/deckz/assets/<hash>`, materialized by
symlink) would make seeding free and share renders across clones; it's the natural
second step once stamps exist, not a prerequisite.

### Finding 4: memory, not CPU, bounds concurrency

The machine has 15 GB of RAM and 8 cores. A large deck's Typst compilation takes about
2 GB and `typst_memory_max` lets it reach 5 GiB. Each `--watch` keeps its processes
alive, and each agent session costs a few hundred MB. `typst_parallel_compilations` is
per deckz process, so two tasks building at once each believe they own the machine.
deckz needs a machine-wide limit, a semaphore of `flock`ed slots in the user cache
dir (`labs/gpu.py` already uses `flock`), shared by every deckz process: studioz's
tasks, agent sessions in the terminal, a person's builds. Roughly two large
compilations at a time here.

### Finding 5: PDFs live where the content is

PDFs are gitignored, per checkout, and a workspace's `.build/` symlinks to its own
assets, so PDFs can't move between checkouts. Since studioz never touches the main
checkout, decks are built and handed out from the workspace that holds the content:
after a Sync, its PDFs match what was pushed, `deckz status` says which are outdated,
and `deckz upload` (which refuses stale PDFs) runs from there.

### Seeding, concretely

A deckz command, usable without studioz: `deckz worktree add <name> [--base <rev>]`
/ `deckz worktree remove <name>`:

1. `git worktree add ../<repo>--<name> -b ws/<name> <base>` (`<base>`: the upstream
   branch, `origin/main` on slides).
2. Copy into it the outputs listed by a new `setup.seed` setting in `deckz.yml` (for
   slides: `assets/typ`, `assets/svg`, `assets/web/vendor`, the video renders), and
   symlink `.env`.
3. Run `deckz setup --check` there: everything present, hooks resolved (slides'
   `core.hooksPath` is the committed, relative `.githooks`, so the worktree's own
   copy runs).

With hash stamps, a seeded output whose source changed in the main checkout's working
tree is simply rebuilt in the workspace. Before stamps exist, step 2 copies only the outputs
whose sources match the base commit in the main checkout's working tree, and resets
their mtimes after the checkout. Good enough for the spike, not for good.

## Workspaces

A workspace ("espace de travail" in the UI; not to be confused with the uv workspace
of "studioz itself") is a worktree (`ws/<name>` branch) plus studioz's state about it: its agent
sessions, checkpoints, preview processes, and the baseline builds of its decks. It
lives as long as the work does, days or weeks, like a Codespace.

- **Opening**: from the home page, "Nouvel espace de travail", named after the work
  ("pnd-2026", "mmd jour 2"); `deckz worktree add` creates and seeds it (about 3 s in the
  spike). A workflow (new deck, QA of a deck) can open one directly.
- **Working**: the person browses the material, edits it by hand (in studioz's editor or
  their own: a workspace is a plain directory, and studioz watches its files whatever
  writes them), or asks the agent. One agent at a time per workspace, since two would
  edit the same files; parallel work goes in another workspace.
- **Checkpoints**: after each agent turn, and on demand, studioz records the workspace's
  state as a git tree written through a private index (`GIT_INDEX_FILE=<tmp> git add
  -A && git write-tree`, under `refs/studioz/<workspace>/`), untracked files included
  and the real index untouched (the refs go with the workspace when it closes).
  "Annuler ce tour" restores one, whatever wrote the
  files: the SDK's own file checkpointing (`rewind_files`) only covers its edit tools,
  and the spike's agent wrote with `cat >>`.
- **Committing**: see below. Nothing is committed implicitly, ever.
- **Staying current**: studioz shows how far the workspace's branch is behind the
  upstream branch and offers to update it (a rebase, see Sync) before it drifts.
- **Closing**: `deckz worktree remove`, refused while there are uncommitted changes or
  commits not synced, unless the person confirms after seeing them.

A workspace costs about 1 GB of disk (the checkout, the seeded outputs, its builds);
the home page shows each one's size and last use.

## Committing and syncing

- **The agent never commits.** Inside a workspace, a studioz `PreToolUse` hook (a
  programmatic one, so terminal sessions keep their own behavior) refuses `git commit`,
  `git push`, and every command that moves the branch or discards changes (`rebase`,
  `reset`, `checkout`/`switch`/`restore`, `stash`, `merge`), with a message saying that
  the person commits from studioz. The repository's own denials still apply on top.
- **Commit** (a button, whenever the person wants): studioz shows the changes since the
  last commit, rendered (see "Previews"), with the checks' verdict, and the files
  grouped by what they are (frames of a deck, a figure, a lab, a video). The person
  can leave files out (file-level selection; hunks inside a file stay out of scope). The
  agent drafts the message on request. When the selection changes one language of a
  fr/en pair only, studioz says so before the hook does and offers the two ways out:
  "translate now" (an agent turn) or "commit anyway" with the reason as the `Lang-sync`
  trailer. studioz then runs `git commit`: the `pre-commit` and `commit-msg` hooks run
  as usual, and a refusal is shown with its fix message, with "ask the agent to fix it".
- **Sync** (a separate button): lists the workspace's commits not on the upstream
  branch, fetches, rebases them onto it (`git rebase --autostash`: the workspace is the
  person's own, so its uncommitted work is carried along), runs `deckz check`, shows
  the result, and pushes after a confirmation (`git push origin HEAD:main` on slides).
  A conflict is never resolved silently: studioz stops the rebase, and the person
  either asks the agent to resolve it (it edits the files; studioz continues the rebase
  once the person has seen the result) or aborts.
- **The main checkout is never touched**: it may hold other sessions' uncommitted work
  (slides' `CLAUDE.md`), and nothing in this flow needs it.

## studioz itself

**studioz**, a Python package in a uv workspace with deckz: the deckz repository becomes
the workspace root, with `studioz/` as a member (its own `pyproject.toml`, `src/studioz/`,
depending on deckz through `deckz = { workspace = true }`). One `uv.lock` and one
checkout keep both in step, and studioz releases with deckz's version (bumpver's file
patterns cover both). deckz's core keeps no dependency on the Agent SDK or the web
stack. slides adds `studioz = { path = "../deckz/studioz", editable = true }` next to
deckz in `[tool.uv.sources]`, so `uv sync` installs both. The workspace section is a
deliberate divergence from the Copier template, recorded in deckz's `CLAUDE.md` like
the others.

It's a local web app started by `studioz` (from slides: `uv run studioz`; it opens the
browser on localhost), on each person's machine, for that person: no accounts, no
server to run. It imports deckz for status, affected decks and paths, and
`claude-agent-sdk` for the agent. Pages are server-rendered (FastAPI, Jinja templates,
htmx, server-sent events for live updates), with two client-side pieces: pdf.js for
the PDF previews and CodeMirror for the editor, vendored into the package as one
pinned bundle at release time (the way slides vendors reveal.js), not a single-page
app with its own build to maintain. Its UI is in French, like
`HANDBOOK.md`. The machine needs what the repository needs, which `deckz setup`
already checks, plus the `claude` CLI logged in (above).

### Screens

- **Home**: the workspaces (name, branch, uncommitted changes, unsynced commits, behind
  upstream by, size, last use), "Nouvel espace de travail", the workflows, and the
  repository's state as `deckz status` sees it from the upstream branch.
- **Workspace**, the main screen, laid out like an editor:
  - left, the **navigator**: the decks and their parts and sections (`deckz show
    paths`), shared sections, figures, labs, videos; and two panels, **Changes**
    (everything since the last commit, rendered) and **Problems** (checks, build errors,
    shrunk frames, translation gaps, live);
  - center, the **preview** of what's selected (see "Previews"), with the editor of its
    source beside or under it;
  - right, the **agent**: the conversation, its progress (to-do list, one-line
    summaries of the commands it runs), question forms, "Annuler ce tour";
  - top bar: Commit, Sync, the deck's build/upload buttons (kinds and languages spelled
    out, never `.env` defaults), the plan's usage, running jobs.
- **Commit** and **Sync**: dialogs over the workspace (see "Committing and syncing").
- **Publish**: labs and videos not published, each with what publishing does, and the
  publish command run directly after an explicit confirmation. Agents can't publish
  (`templates/hooks.py` denies it); studioz keeps it that way.

### Interacting with the material

The preview isn't only for looking:

- **Click a frame** to open its source at its `# Title` (from `deckz show frames`, which
  maps each page to its frame, file and line).
- **Comment on a frame** (or a figure, or a lab cell): the comment becomes an agent
  instruction that names exactly what it points at ("this frame, `content/.../x.md`,
  frame 'Sélectionner des lignes avec `.loc`'"), the way review comments work in a
  design tool. Several comments can go in one instruction.
- **Edit by hand** in the editor: Markdown with deckz's syntax highlighted, saved files
  checked at once (the post-edit checks, shown in Problems) and rebuilt by `--watch`.
- **Open in my editor**: for people who have one, the workspace path and a link that
  opens it there; studioz follows those edits too.

### Previews

Everything a workspace changes can be seen rendered before it's committed. Measured on
`orsys/pnd`: a `--watch` rebuild shows 0.5 s after a save, the HTML deck builds in
5.2 s, and pdftocairo turns 120 pages into images at 50 dpi in 1.3 s.

| What changes | Live preview | Before/after since the last commit |
|---|---|---|
| Slides | the deck's handout PDF in pdf.js, reloaded at the same page after each `--watch` rebuild (or the reveal.js HTML in an iframe, opened at the same slide) | pages turned into images, matched by frame title (`deckz show frames`) so an inserted frame doesn't shift every comparison; changed frames side by side, new and removed ones marked |
| Shared content | the same, in the deck the person is working on | same, plus the list of other decks it reaches (`deckz show affected`), each with an optional build |
| Translations | fr and en of the selected frame side by side, from the two builds | fr/en pairs whose other language didn't change, flagged |
| Deck structure (`deck.yml`, flavors) | the outline (`deckz show tree`) | outline before/after |
| Typst figures, plots | the SVG the assets build writes, refreshed on change | old and new SVG side by side |
| Videos | the last render; a draft (`--quality l`, 480p15, minutes) on request | old and new render; the full-quality render is a job, run before Sync or after |
| Labs | the notebook rendered as a page (nbconvert) | a rendered notebook diff, outputs included (nbdime); refreshing a demo's outputs is a job (GPU), shown when it ends |

**Baselines.** "Before" is the build at the workspace's last commit. When the person
commits, studioz keeps the current builds of the decks they touched as the new
baselines (`.run/studioz/baselines/`, keyed by commit). When a deck has no baseline
yet, studioz builds the committed version in the background in a scratch worktree
(seeded, so about 3 s plus the build).

A large deck keeps its `--watch` processes alive at a few GB: studioz watches only the
deck in front of the person, stops it when they leave it, and goes through the
machine-wide compile limit like every other build.

### Workflows

Declared by the repository, so studioz stays generic:

```yaml
studioz: # read by studioz; deckz ignores the section
  workflows:
    - name: { fr: Nouvelle formation, en: New training }
      skill: nouvelle-formation
      inputs:
        - { name: program, kind: file, label: { fr: Programme (PDF ou Markdown) } }
      prompt: "Crée la formation à partir du programme {program}."
    - name: { fr: Relire un deck (QA) }
      skill: qa-formation
      scope: deck # launched from a deck's page, `{deck}` filled in
      prompt: "Fais le QA de {deck}."
      then: qa-fix # the workspace then offers "Appliquer les corrections"
```

A workflow is a form, a prompt naming the skill, and where its output lands. The skill
still decides everything else, including which questions to ask.

### Agent configuration

- `cwd` = the workspace, `setting_sources=["project"]`, auto memory off, the system
  prompt preset `claude_code` with a short appended note (a workspace the person
  commits from themselves, a person who knows the content but not the tooling, answer
  in French), and the cache variables of Finding 2.
- The commit-and-branch denials of "Committing and syncing", as a programmatic
  `PreToolUse` hook; a checkpoint after each turn.
- One conversation at a time per workspace, resumed across visits (`resume=`), so the
  agent keeps the context of the work; "Nouvelle conversation" starts a fresh one.
- `permission_mode="auto"`, plus the Claude Code command sandbox limiting writes to the
  worktree (and `.run/`), and the repository's `PreToolUse` denials unchanged. A tool
  call the classifier won't allow is denied with a message, never shown to the person.
  Allow rules for the routine commands (`deckz *`, `uv run deckz *`, read-only git)
  go in the committed `.claude/settings.json`, so terminal sessions benefit too. In
  the spike, `auto` with the sandbox's `autoAllowBashIfSandboxed` sent nothing but the
  skill's question to `can_use_tool`, a write into the main checkout failed, and a
  commit (which writes into the shared `.git`) worked.
- **The post-edit check must not depend on the tool used.** With Bash auto-allowed,
  the spike's agent wrote its frame with `cat >>`, so the `PostToolUse` hook on
  `Edit|Write` never ran. The pre-commit hook still catches the mechanical checks, but
  the agent learns late. deckz's `stop` hook should run the post-edit checks on every
  content file the worktree changed (`git diff`), whatever wrote it.
- Answers to a deferred question come from `can_use_tool` on resume: in the spike, a
  `PreToolUse` hook's `allow` with the answers in `updatedInput` was overridden by
  `can_use_tool`, which still fires for `AskUserQuestion`. Deferral only works when
  the agent made a single tool call in that turn (documented); otherwise the question
  arrives live and the callback simply waits.
- `max_budget_usd` per workflow, as a guard against a runaway run; the workspace shows
  the agent's usage as it runs, and pauses on the plan's rate limit (see "Credentials").
- Labs on a rented GPU (`deckz labs gpu`), Manim renders and full builds go through the
  studioz's job queue, which respects the machine-wide compile limit and shows each
  job's log in the workspace.

## What a non-expert can expect

| Task | Expected autonomy |
|---|---|
| Status, build, upload, publish | Complete: buttons over deckz |
| New deck from a program | High: file plus a few answers, review the rendered deck |
| Edit or add slides, by hand or by instruction | High: live preview, comments on frames, undo per agent turn |
| QA, then fixes | High: findings as a checklist, decisions as forms, rendered diff |
| fr/en sync | High: backlog, translate, side-by-side review |
| New figures (CeTZ, plots) | Medium-high: judged visually, iterated by comments |
| Labs (create, run on GPU, write outputs back) | Medium: long runs, GPU rental cost, notebooks harder to review |
| Manim videos | Medium: slow render loop |
| Theme, filters, deckz, build failures nobody understands | Low: "hand over to an expert" gives the workspace's path and session ID, for a terminal session in it |

## Phases

Each phase is usable on its own and released like the operability phases.

### Phase 0: spike (a few days, throwaway)

On slides, by hand, logged in with a Pro plan: `git worktree add`, seed, shared venv, one `deckz run` and one
`--watch` in the worktree; one Agent SDK session there with the settings above running
`qa-fix` on a small deck, its `AskUserQuestion` answered from a script; a `defer` and a
resume. Measure: time to a ready worktree, first-build time, peak memory of two
concurrent tasks, and how much of a Pro window a `qa-formation` pass on a mid-size
deck uses. Answers: does `UV_NO_SYNC` plus `UV_PROJECT_ENVIRONMENT` hold, do
all hooks fire in the worktree, and does `auto` mode with the sandbox leave the
routine commands unprompted.

**Status (2026-10-10): done**, on slides at 71de77d0, worktree `../slides--spike`
(branch `task/spike`), scripts in the session's scratchpad. Results:

| Question | Result |
|---|---|
| Worktree ready | `git worktree add`: 2.6 s (692 MB); seeding (`cp -a` of `assets/typ`, `assets/svg`, `assets/web/vendor`, video renders, `.env` symlinked): 0.5 s |
| Seeded outputs fresh? | No: with copied times, 7/7 videos and 266/266 figures stale (Finding 1). After `touch`, 0 stale (sources clean in the main checkout) |
| Committed plots | All 101 rebuilt and modified on first build (Finding 1): a bug for every fresh clone |
| Shared venv | Works: no `.venv` created, paths in the worktree; under the sandbox, needs the cache variables (Finding 2) |
| Build times | `orsys/pnd` handout: 175 s first (almost all the spurious plot rebuild), 2.7 s after; Fortinet first build 5.4 s; `--watch` rebuild seen 0.5 s after an edit; small decks peak 0.3-1 GB |
| Git hooks in the worktree | Fire: `commit-msg` refused a one-sided commit (`Lang-sync`), `pre-commit` refused a `{=latex}` block, both with their fix messages |
| Claude hooks | `PreToolUse` fired on every Bash call; `PostToolUse` post-edit skipped by a `cat >>` write (see "Agent configuration") |
| Agent task | "Add a frame to the MultiIndex chapter of `orsys/pnd`, ask me `.loc` or `.xs()` first, check the handout builds, commit": 126 s, 16 turns, $0.50 at API prices; asked the question, ported to English unprompted, built fr and en, checked overflow, committed (`c0bcfa34`) |
| Permission prompts | None: only `AskUserQuestion` reached `can_use_tool` (`auto` + sandbox) |
| Sandbox | Write into the main checkout: refused; commit from the worktree: works |
| Deferred question | Works across processes: `stop_reason=tool_deferred` with `deferred_tool_use`, resumed by `resume=<session>`, answered from `can_use_tool` |
| Plan usage | Five-hour window 48 % → 52 % during the task on the user's account (an upper bound: this session shared the window) |
| Agent memory | Claude processes peaked at 1.17 GB, this session's included: about 0.5 GB per task |

Not measured: a `qa-formation` pass on a mid-size deck (worth doing on the first real
QA rather than on a throwaway one), and two large decks building at once (known from
earlier work: about 2 GB each, `typst_memory_max` at 5 GiB).

### Phase 1: deckz prerequisites (useful without studioz)

1. Hash stamps instead of mtimes: deckz's video renders and Typst figures, and the
   builder protocol's documentation; slides' plot and SVG builders follow, writing
   reproducible PDFs. Urgent on its own: a fresh clone's first build dirties 101
   committed plots today.
2. `deckz worktree add/remove` and `setup.seed`.
3. A machine-wide compilation limit (`typst_machine_compilations`, flock slots in the
   user cache dir).
4. `deckz show frames` (each page of a built PDF → its frame, file and line), for the
   before/after view and click-to-source.
5. The `stop` hook runs the post-edit checks on every content file the worktree
   changed, whatever wrote it.

### Phase 2: workspaces without agents

The uv workspace (deckz root, `studioz/` member) and slides' dependency on it. Home,
workspaces (open, seed, close), the navigator, live previews of decks and figures,
the editor, Problems, Changes with baselines and before/after, Commit, Sync,
build/upload/publish with confirmations, the job queue. This alone gives the
colleague who doesn't want agents a Codespace-like way to do everything in
`HANDBOOK.md`.

### Phase 3: the agent in a workspace

The conversation panel, question forms, comments on frames as instructions,
checkpoints and "Annuler ce tour", the commit denials, usage display and rate-limit
pauses, the agent drafting commit messages and resolving Sync conflicts.

### Phase 4: workflows

`studioz.workflows` in `deckz.yml`, opening a workspace from a workflow, `defer` for
questions answered later, the QA → fix chain (findings as a checklist in the
workspace), the translation backlog as a list to work through.

### Phase 5: long jobs and the remaining previews

Labs on GPU (notebook previews and diffs), Manim drafts and full renders, `deckz run
decks`, through the queue, with notifications when they end.

### Then, with the colleague

The acceptance test the operability plan already plans, extended: the colleague does a
week's real tasks through studioz, and every time they get stuck becomes a fix in
deckz, a skill, or studioz, in that order of preference.

## Risks

- **Judging content.** studioz proves a change builds, passes the checks and fits
  its frames; not that a fix is right or a translation faithful. The colleague's domain
  knowledge covers it only if the review shows why each change was made (the QA finding
  next to its fixed frame).
- **Plan limits and duration.** A QA pass with subagents on a large deck, or a
  translation backlog, runs for tens of minutes and may exhaust a Pro window. Visible
  usage, resumable pauses, and a lighter model or effort for the reading subagents
  are required, not optional. A person who often hits the limit needs a larger plan.
- **Terms.** The credential setup follows Anthropic's terms as read on 2026-10-10
  (each person's own login, unmodified binary, studioz never handling credentials);
  re-read them when they change.
- **Drift.** Workflows tempt people into putting instructions in their `prompt:`. That
  belongs in the skill; the review of a new workflow checks it.
- **Machine load.** Even with the compile limit, two watches and a GPU queue on a
  15 GB machine is tight. studioz watches only the deck in front of the person,
  shows memory, and holds new jobs over a threshold.
- **Long-lived workspaces drift.** A workspace kept for weeks diverges from the
  upstream branch and conflicts at Sync. studioz shows how far behind it is and
  offers the update early; the agent helps with conflicts, but the person sees the
  result before it's kept.
- **SDK churn.** The Python SDK's `can_use_tool` workaround and `defer` are recent;
  the spike pins a version and studioz's tests cover the question round trip.

## Decisions (2026-10-10)

1. **Packaging**: studioz, a member of a uv workspace rooted at the deckz repository;
   deckz's core doesn't depend on it.
2. **Credentials**: each person's own Claude subscription (Pro is the baseline), through
   their `claude` login; no API key. See "Credentials".
3. **Where it runs**: on each person's machine, for that person.
4. **Commit vs push**: committing and pushing (Sync) are two separate decisions of the
   person's.
5. **Scope**: every routine task, shared content included, with the decks a shared
   change reaches listed in the review. Out of scope: theme, Lua filters, deckz itself,
   `pyproject.toml`/`uv.lock` (expert work, in a terminal).
6. **A Codespace-like experience** (2026-10-10, after the spike): long-lived workspaces
   where the person works on the material with live previews, by hand or with the
   agent, and commits only when they decide; the agent never commits, and studioz
   never touches the main checkout. Replaces the earlier per-task Accept/Discard.
