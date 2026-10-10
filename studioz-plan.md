# studioz plan: a UI for operating a deckz repo, agents included

## Where things stand, and how to resume (2026-10-10)

**Done:** phases 0, 1 and 2 (workspaces without agents: increments 1 to 8 under
"Phase 2"), and phase 3 (the agent in a workspace: increments 1 to 5 under
"Phase 3"). **Next:** phase 4, workflows (see "Phase 4"); first, a trial of
phase 3 by the user on real work. `git log origin/main..main` in
`../deckz` (and in `../slides`, for its `uv.lock`) lists what isn't pushed;
nothing is released since 31.3.3. Push and release are the user's call.

### Code map

studioz is `studioz/src/studioz/` (deckz's `CLAUDE.md`, "studioz", has the
architecture):

| Module | Does |
|---|---|
| `app.py` | every route (FastAPI, server-rendered Jinja in French, htmx) and the `Studio` holding the long-lived parts |
| `workspaces.py` | the home page's view of `deckz worktree`'s worktrees |
| `watches.py` | one `deckz run --watch` per workspace for the deck on screen; `environment()`/`workspace_environment()` for every command run in a workspace |
| `sources.py` | what the editor may read and save (never over a version it didn't read, keeping line endings) |
| `background.py` | commands rerun when a workspace's files change (`deckz status`, `deckz show affected`); `git status` parsing |
| `problems.py`, `changes.py` | the navigator's Problems and Changes panels; `changes.LangPairs` caches deckz's fr/en pairs |
| `baselines.py`, `comparison.py` | handouts as of the last commit, frame-by-frame before/after |
| `commits.py`, `sync.py` | the Commit and Synchronisation dialogs |
| `jobs.py`, `actions.py` | the job queue; build, upload, publish |
| `agent.py` | each workspace's agent conversation (Agent SDK): options, the git refusal hook, questions, the transcript |
| `checkpoints.py` | the workspace's files before and after each agent turn, and undoing the last one |
| `asks.py` | what the dialogs ask the agent (prompts), and the proposed commit message |
| `static/` | `deck.js` (pdf.js viewer, comparison), `editor.js` (CodeMirror), `dialogs.js` (dialogs opened from reloading panels), `agent.js` (the agent panel), vendored JS (`uv run doit vendor`) |

Tests: `studioz/tests/`, against temporary repositories, a fake `deckz` (a script
in the workspace's `.venv/bin/`), a local bare remote and a fake Agent SDK client
yielding the SDK's own message objects; nothing in them touches the network.

### Developing and trying a change

- Work in the worktree `../deckz-studioz` (branch `studioz`), never in `../deckz`
  (live for slides: deckz's `CLAUDE.md`, "This working tree is live"). Check with
  `uv run doit check test` there; when finished, commit there (the pre-commit hook
  runs the same) and fast-forward `../deckz` (`git merge --ff-only studioz`). Before
  merging a change of behavior, tell the running slides sessions (`ListAgents`).
- Try it on slides: from the worktree, `uv run --quiet studioz --workdir
  ../slides --port 8431 --no-browser`, then <http://localhost:8431/>. The dev
  workspace is `studioz-dev` (`../slides--studioz-dev`, branch `ws/studioz-dev`,
  clean at `697e9401`, one commit behind `origin/main`); the Fortinet deck
  (`orsys/INTRA/2026-10-fortinet`) is the usual test deck. Leave it clean: a scratch
  commit comes back off with `git reset --soft 697e9401 && git reset -q` (or the new
  base after an update), and files are restored from a copy taken first.
- A workspace runs its own deckz, installed from `../deckz` (main). To try deckz
  changes from the worktree, point the workspace at it for the trial:
  `.venv/lib/python3.12/site-packages/deckz.pth` holds
  `/home/mog/repos/shuuchuu/deckz/src`; write
  `/home/mog/repos/shuuchuu/deckz-studioz/src` there, and put it back after.
- Never click "Publier" (labs, videos, or Sync's push) nor "Envoyer" on slides: they
  publish to trainees, slides' origin or Google Drive. The tests cover them with
  fakes; on slides, stop at the confirmation.
- The browser (Claude in Chrome) needs Claude Code started with `claude --chrome`.
  The navigator's panels reload themselves, so an element found then clicked a
  second later may have moved: click from a script (`javascript_tool`) once the
  page has settled. Typing into CodeMirror goes through its Markdown mode (Enter
  continues a list): to change a file's content, write it on disk, the editor
  follows.
- A shell with deckz's own `.venv` active runs that deckz from slides' git hooks
  (they take `deckz` from the `PATH`), whose Python lacks slides' plotting
  libraries: the `python` check then fails. Commit in a workspace with its
  `.venv/bin` first on the `PATH` (as studioz does), or from studioz.

### Open items

Found along the way, not done (each increment's "Left" has the rest):

- A broken Jinja tag (`{{ x`) passes `deckz check` (and so the pre-commit hook);
  it fails only at build. A deckz check that renders each content file would catch
  it.
- `tests/test_deck_builder.py::test_interrupt_does_not_wait_for_running_compilations`
  failed once in about 20 full runs, under load: a timing test (a 0.5 s sleep),
  not looked into yet. (`test_labs_gpu.py::test_queue_kills_what_a_run_leaves_running`
  failed the same way: it checked a process gone right after `kill -9`, which
  returns before the process exits; it now waits.)
- deckz's messages are in English in a French UI; the lab checks read every notebook
  again each (6 of `deckz status`'s 10 s on slides).
- The Commit dialog's draft is lost when the page changes; jobs don't survive a
  studioz restart, and their end isn't notified beyond the top bar's colour.
- The untracked `.claude/` in `../deckz` is the frontend plugin's install: the
  user's, kept, never committed.
- slides depends on studioz (editable): a new studioz dependency makes slides'
  `uv.lock` stale, and the next `uv run` there rewrites it. Merge such a change
  with a `uv lock` committed in slides at once (as `1cf2de1d` did for
  `claude-agent-sdk`); each workspace's own `uv.lock` follows when it syncs.
- The agent writes its commands' descriptions in English, although the appended
  prompt asks for French; and a command failing for an ordinary reason (`grep`
  finding nothing, exit 1) shows as "Refusé ou en échec".

### Phase 3's increments

Read "Running agents", "Credentials", the spike's results (phase 0) and "Agent
configuration" first: they hold what was checked and measured (the spike's scripts
are gone). studioz pins `claude-agent-sdk==0.2.160` (bundling Claude Code
2.1.283). Each a usable increment:

1. **The conversation panel**: done (see "Phase 3"), with the commit and branch
   refusals and `auto` permissions in the sandbox, planned for 3.
2. **Questions**: done (see "Phase 3").
3. **Guardrails**: done (see "Phase 3").
4. **Usage**: done (see "Phase 3").
5. **The agent in the existing dialogs**: done (see "Phase 3").

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
| `.venv/` | 3.1 GB apparent, 27 MB on disk | `uv sync` (hard links from uv's cache) | 0.8 s with a warm cache |
| `.env` (`DECKZ_*` defaults, lab secrets) | — | user-level `~/.config/deckz/.env` | — |

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
editable = true}`. A worktree outside `shuuchuu/` breaks that path, so worktrees go
next to the repository (`../slides.tasks/<task>` breaks `../deckz`; `../slides--<task>`
doesn't).

**Each workspace has its own environment** (decided 2026-10-10, after the first
version of `deckz worktree` linked the main checkout's `.venv`). A shared environment
breaks the invariant that workspaces are independent: once either checkout's
`uv.lock` changes, `uv run` in one re-syncs the environment to its lock and the other
silently runs with the wrong versions; a `uv sync` in a workspace changes the main
checkout's; and under the sandbox, the environment is outside the writable
worktree. Measured, a workspace's own `uv sync` costs 0.8 s and 27 MB on disk: uv
hard-links from its cache (same disk), and pycairo's wheel is built once and cached.
slides declares it as a `setup.steps` entry, and `deckz worktree add` runs `deckz
setup` in the new worktree. The spike's alternative (`PATH`, `UV_PROJECT_ENVIRONMENT`
and `UV_NO_SYNC` pointing at the main checkout's environment) is dropped.

Under the sandbox, `~/.cache` is read-only, which breaks `uv run` (it takes a lock in
its cache) and makes matplotlib warn, so the workspace's caches live in its gitignored
`.run/cache` (`UV_CACHE_DIR`, `XDG_CACHE_HOME`, `MPLCONFIGDIR`); with them, `uv run`
in the workspace syncs nothing (the environment was synced when it was created).

What every checkout shares (one's credentials and defaults) goes in the user-level
`~/.config/deckz/.env`, which deckz reads after the checkout's own `.env`: nothing is
linked between checkouts.

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
deckz needs a machine-wide limit, a semaphore of `flock`ed slots in the user's
runtime dir (`labs/gpu.py` already uses `flock`), shared by every deckz process: studioz's
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
2. Copy into it the main checkout's ignored files under `deckz.yml`'s `worktree.seed`
   (for slides: `assets/typ`, `assets/svg`, `assets/web/vendor`, `assets/videos`).
   Nothing is linked (see Finding 2).
3. Run `deckz setup` there (its own environment: `uv sync`), then everything is
   present, hooks resolved (slides'
   `core.hooksPath` is the committed, relative `.githooks`, so the worktree's own
   copy runs).

With hash stamps (done), a seeded output whose source changed in the main checkout's
working tree is simply rebuilt in the workspace. Step 2 copies each output with its
`.stamp` and keeps file times, so an output with no stamp looks older than the
workspace's freshly checked-out sources and is rebuilt, not adopted.

**Done** (2026-10-10): `deckz worktree add/list/remove` (`deckz.worktrees`). On
slides: 3.5 s, 1,425 files copied, `deckz setup --check` all ok in the worktree. The
trial found the Typst figures' stamps too coarse (every `_`-library counted for every
figure, so another session's untracked `_impromptu.typ` in the main checkout made all
258 SVGs rebuild): each figure's stamp now covers only the files it references.

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
| Shared venv | Works: no `.venv` created, paths in the worktree; under the sandbox, needs the cache variables. Superseded: each workspace has its own environment (Finding 2) |
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
   reproducible PDFs. Urgent on its own: a fresh clone's first build dirtied 101
   committed plots.
   **Reproducible plots: done** (slides a1713041, 2026-10-10): each plot gets fresh
   rcParams and a fixed NumPy seed, no creation date (Kaleido's is overwritten), and
   the plots seed their own randomness; all regenerated once, every one rebuilding to
   the same bytes except `membership-time` (it times real code).
   **Hash stamps: done** (2026-10-10): `deckz.stamps` (`<output>.stamp`, a digest of
   the inputs' bytes; an unstamped output newer than its inputs is adopted, so the
   switch rebuilt nothing). The Typst figures (figure, libraries, theme, language),
   the video renders (the scene and the repo modules it imports, closing the
   `--force` gap) and slides' plots and SVG mirrors use it; the plots' stamps are
   committed, so a fresh clone rebuilds none and cross-machine bytes no longer
   matter. Seeding a workspace copies the stamps with the outputs.
2. `deckz worktree add/remove` and `worktree.seed`. **Done** (see "Seeding,
   concretely").
3. A machine-wide compilation limit (`typst_machine_compilations`, flock slots).
   **Done** (2026-10-10): `components/machine_slots.py`; the slots live in
   `$XDG_RUNTIME_DIR/deckz/`, not the cache dir, since the sandbox redirects
   `XDG_CACHE_HOME` into each worktree; a sandboxed process opens existing slot
   files read-only (`flock` allows it). A slot is held only while compiling: idle
   `--watch` workers keep their memory without one.
4. `deckz show frames` (each page of a built PDF → its frame, file and line), for the
   before/after view and click-to-source. **Done** (2026-10-10): the deck build adds
   an invisible `<deckz-frame>` marker after each frame heading (fragment, heading
   index, `here().page()`) on the copy it converts; `show frames` queries the build
   (about 4 s on an 85-page deck: a full compile). The PDF is unchanged (same text
   on orsys/INTRA/2026-10-fortinet), and every one of its 63 frames maps to the
   right page. For studioz, writing the frames next to the PDF at build time (the
   `--watch` worker's compiler is warm) would make the lookup free.
5. The `stop` hook runs the post-edit checks on every content file the worktree
   changed, whatever wrote it. **Done** (2026-10-10): `stop_report` checks every
   content file the session changed that the post-edit hook hasn't passed as it is
   now (the post-edit hook records what it found clean, so edit-tool sessions pay
   nothing extra); the session-start snapshot includes uncommitted content files,
   so another session's are left alone.

### Phase 2: workspaces without agents

The uv workspace (deckz root, `studioz/` member) and slides' dependency on it. Home,
workspaces (open, seed, close), the navigator, live previews of decks and figures,
the editor, Problems, Changes with baselines and before/after, Commit, Sync,
build/upload/publish with confirmations, the job queue. This alone gives the
colleague who doesn't want agents a Codespace-like way to do everything in
`HANDBOOK.md`.

**Increment 1: done** (2026-10-10): the uv workspace (slides depends on studioz),
`uv run studioz` serving the home page (each workspace with its uncommitted
changes, unsynced commits, how far behind the upstream branch, size, last use;
create, which runs `deckz setup` there; close, refused while it holds work, then
forced after a confirmation) and a workspace page with its decks and changes. The
JavaScript is pinned in `studioz/package.json` and committed into the package
(`doit vendor`), not built at release time, so that the editable install from
slides needs no npm. Measured on slides: a workspace is ready in 7 s and frees
915 MB when closed (its `.venv` counts 3 GB, all but 6 MB hard links into uv's
cache). A local web app can be driven by any website open in the browser, so
studioz refuses requests not naming a local host and changes not coming from its
own pages (`studioz.local_only`).

**Increment 2: done** (2026-10-10): a deck's page shows its handout live, in
pdf.js (6.3, vendored with htmx), fr or en. Opening it starts the workspace's
`deckz run --watch` of that handout alone (one watch per workspace, the
workspace's own deckz, every option spelled out); the page follows it through
server-sent events (building, up to date, failed with the error), reloads the
PDF at the same scroll position after each build, and the watch stops 30 s
after no page follows it, or when studioz stops. Measured on
orsys/INTRA/2026-10-fortinet in a fresh workspace: first build 6 s, an edit
shown 3.5 s after the save, a failure 3 s. The page exposed a deckz gap: a
Jinja error named no file; it's now a `RenderError` with the content file and
line (deckz d75292b).

**Increment 3: done** (2026-10-10): a click on a page of the preview opens its
frame's source at its `# Title` in an editor beside the PDF (CodeMirror 6,
Markdown with the Jinja tags marked, or YAML), fr or en. The lookup is instant
because each Typst compilation now records its frame markers next to its PDF
(about 50 ms per rebuild), so `deckz show frames` no longer compiles the
document again; studioz never queries a build itself. Ctrl-S saves into the
workspace, where the watch rebuilds; a save never overwrites a version of the
file the editor didn't read (the person chooses: reload, or keep theirs), and
the editor follows changes made elsewhere while it has none of its own.
Measured on orsys/INTRA/2026-10-fortinet: the editor opens 0.2 s after the
click, a save shows in the PDF 3.5 s later. The record exposed a typst 0.15
quirk: a compilation after a query misses the edits made since, so a worker
queries before compiling. Left for later increments: the post-edit checks of
a saved file (Problems), the reverse way (from the editor to the page), and
the other files' editors (figures, `deck.yml` from the navigator).

**Increment 4: done** (2026-10-10): the navigator's Problems panel, live.
Workspace-wide: the workspace's own `deckz status` (its content checks, what
its changes leave to translate, labs and videos not published), run in the
background when the page opens and again whenever the workspace's files
changed (`git status`, 20 ms, decides), so after each save; it takes 13 s on
slides, the checks being most of it. For the deck on screen: its build's
failure, and the frames its build shrank to fit. Each problem naming a file
opens it in the editor at its line, and a shrunk frame also brings the PDF
to its page. deckz changes: every compilation now records the theme's
shrunk-frame and table markers with the frames (`<main>.markers.json`), so
`deckz check overflow` gives each shrunk frame's line and no longer
compiles (0.6 s instead of 2.6 s on the Fortinet deck, both languages);
`deckz status` sections carry a stable `key`, and `--no-decks` skips the
built decks (8 s when a change reaches many decks), which studioz doesn't
show: they are for the build and upload increment. Left: deckz's messages
are in English in a French UI, and the lab checks (6 of the 10 s) each read
every notebook again.

**Increment 5: done** (2026-10-10): the navigator's Changes panel, live
(everything since the last commit, grouped: a deck's own files, shared
content, labs, videos, images and theme, the rest; a content file or
notebook whose other language didn't change is flagged; the decks the
changes reach, from the workspace's `deckz show affected`, 7 s, in the
background), and a deck's "Avant/après" view: the frames changed since the
last commit side by side (pdf.js), new and removed ones marked, a frame
replaced in place shown with both titles, a click on "after" opening its
source. Frames are matched by title (`difflib`) from what each build
recorded, and compared on 40 dpi grayscale renders (`pdftoppm`, 0.2 s for 85
pages) minus the bottom right corner, where the frame number changes after
an insertion. Baselines (`.run/studioz/baselines/<commit>/`): the live
build when it finishes on a workspace with no change, else a build of the
commit in a scratch checkout `<workspace>.baseline` (seeded from the
workspace with deckz's now public `worktrees.seed`, removed afterwards):
17 s on the Fortinet deck (checkout 2.6 s, seeding 0.3 s, build 9.8 s).
Left: keeping the current builds as baselines at commit (Commit increment),
only frame pages are compared (not the outline or dividers), figures'
and labs' before/after, and the comparison ignores a theme placing its
frame number elsewhere.

**Increment 6: done** (2026-10-10): Commit, a dialog opened from the
Changes panel: the files changed, grouped as in the panel and all chosen
(file-level selection; a file that changed after the dialog opened is
listed, never committed unseen), the checks' verdict from the Problems
panel, the message, and, when the selection changes one language of a
fr/en pair only, the hook's two ways out but porting: "pending" or
"nothing to port, because…", written as the `Lang-sync` trailer. The rule
is deckz's own (`i18n_stale.one_sided`, now shared by the commit-msg hook,
CI, `deckz status` and the agent hooks, and by the Changes panel instead of
its own copy); finding the pairs takes 1.2 s on slides, so studioz keeps
them while the workspace's layout stays the same. studioz commits the
chosen files as they are on disk (whatever was staged in a terminal is
unstaged first), with git's hooks run by the workspace's own deckz; a
refusal is shown with deckz's message and fix, the message kept. The deck
on screen's live build becomes the new commit's baseline when the commit
leaves no change. Refused during a rebase, a merge or a conflict.
Measured on slides: the dialog opens in 1.8 s the first time, 0.2 s
after; a commit takes 20 s, nearly all of it `deckz check --staged` (16 s);
a `{=latex}` block was refused with `raw-latex`'s message. It exposed a
deckz gap: a broken Jinja tag (`{{ x`) passes `deckz check`, and fails only
at build. Left: the agent drafting the message, "translate now" and "ask
the agent to fix it" (phase 3); the draft is lost when the page changes;
the commit runs while the dialog waits (20 s), not in the job queue.

**Increment 7: done** (2026-10-10): Sync, a Synchronisation panel in the
navigator (commits to publish, how far behind the upstream branch as last
fetched, a rebase stopped on a conflict) and its dialog. "Mettre à jour"
fetches and rebases the workspace's commits onto the upstream branch (the
main checkout's: `origin/main` on slides), uncommitted work carried along
(`--autostash`). A conflict stops there: the dialog lists the files, which
open in the editor beside the PDF; "Continuer" is refused while a conflict
marker is left, "Abandonner" puts everything back. "Mettre à jour et
vérifier" then checks the commits as they would be pushed, whatever the
workspace's files are: `deckz check --staged` with a temporary index holding
the commit (`GIT_INDEX_FILE`, no deckz change needed), and the `Lang-sync`
rule on each commit (`deckz hooks check-commits`, as CI). Only then
"Publier N commits sur origin/main": exactly the commit checked, refused if
the workspace's HEAD moved since, never forced (a push rejected because the
upstream moved asks for an update first). The main checkout's files and
branch never move. It exposed a deckz gap: a worktree stopped in a rebase
has a detached HEAD, so `deckz.worktrees` didn't list it (studioz lost the
workspace while its conflict was being fixed); it now reads the rebase's
branch. Also: the dialogs' opening request now belongs to the dialog
(`static/dialogs.js`), since htmx drops the answer to a button that a
panel's reload removed meanwhile. Measured on slides: fetch and checks of
one commit, 25 s; nothing was pushed to slides' origin (the push is tested
against a local bare remote). Left: "ask the agent to resolve the conflict"
(phase 3); a conflict in the uncommitted work brought back after the
rebase (`--autostash`) is only reported, its files left with markers and a
copy in `git stash list`.

**Increment 8: done** (2026-10-10): build, upload, publish, and the job
queue. A deck's page has "Construire…" (each output and language a
checkbox, spelled out as `deckz run --handout --no-presentation … --sync
--lang …`) and "Envoyer…" (the PDFs `deckz upload --dry-run --json` lists,
new in deckz, the outdated ones marked and the upload disabled while there
are, since deckz would refuse them; a remote file with no local PDF is
deleted, said before). The top bar has "Publier…" (labs and videos not
published, from the workspace's `deckz status`, with what publishing
replaces, and a warning when the workspace's commits aren't on the
upstream branch yet) and the jobs' summary, which opens their logs. Jobs
(`studioz.jobs`) run the workspace's own deckz, one at a time per
workspace, in order, stoppable (SIGINT, then SIGKILL), their logs without
deckz's code locations; they last as long as studioz. It exposed a deckz
gap: two builds of one deck (the page's `--watch` and a full build, or two
terminals) wrote the same fragments and PDFs at once; each compilation now
holds a per-deck `flock` (`.build/.lock`), the second one logging that it
waits. Measured on slides: the upload preview takes 0.8 s, an incremental
full build of the Fortinet deck in French a few seconds; nothing was
uploaded or published (both tested against a fake deckz). Left: desktop
notifications when a job ends (the summary changes colour), jobs surviving
a studioz restart, the videos' renders and labs on GPU (phase 5).

### Phase 3: the agent in a workspace

The conversation panel, question forms, comments on frames as instructions,
checkpoints and "Annuler ce tour", the commit denials, usage display and rate-limit
pauses, the agent drafting commit messages and resolving Sync conflicts.

**Increment 1: done** (2026-10-10): the conversation panel. Every workspace
and deck page has an "Agent" column (foldable, the choice kept per browser):
the transcript (the person's messages, the agent's text, each tool use on one
line in French with its command or file, failures and refusals, how each turn
ended), a message box (Enter sends), "Arrêter" during a turn, and "Nouvelle
conversation" (a second click confirms). `studioz.agent` holds one Agent SDK
conversation per workspace, in the workspace (`cwd`), with the repository's
project settings only, auto memory off, the `claude_code` system prompt plus a
French note (answer simply, say what changed file by file, never commit, ask
questions in the reply), `permission_mode="auto"` in Claude Code's sandbox
(Bash auto-allowed there), the workspace's own `.venv` and caches under
`.run/cache/`. A `PreToolUse` hook refuses `git` commands that commit, push,
pull, rebase, reset, check out, stash, merge or move branches and tags (read-only
`git branch`, `tag -l`, `worktree list` pass); a tool call the permission rules
would ask about is denied with a message. The login is the person's own
(`claude auth status --json`, the bundled CLI, checked every 5 min; otherwise the
panel says to run `uv run studioz login`, the bundled CLI's `auth login`), `ANTHROPIC_API_KEY` is removed at start. The
session id and the transcript are kept in `.run/studioz/agent/`, so the
conversation resumes after a studioz restart (`resume=`); the Claude Code
process (about 0.5 GB) stops after 15 min idle, and with studioz. The page
follows the conversation through server-sent events, and refreshes the
navigator's panels and the before/after view when a turn ends. Two fixes
came with it: `local_only` is now a plain ASGI middleware (Starlette's
`BaseHTTPMiddleware` logged an error each time a page closed an event
stream), and Ctrl-C ends the pages' event streams (`Studio.closing`) instead
of waiting for the pages to close (the deck page's stream did too). Measured
on slides (`studioz-dev`): a first turn reading a deck file, 19 s including
Claude Code's start; a short resumed turn, 4 s; the agent asked to `git commit
--allow-empty` was refused by the hook and said so, no commit made. Left: the
other increments; a turn's usage (increment 4).

**Increment 2: done** (2026-10-10): question forms. A question the agent asks
(`AskUserQuestion`, as slides' skills do, and as the appended prompt now says
for a choice) shows above the message box as a form: each question with its
header, its options and their descriptions (radio buttons, or checkboxes when
several answers are allowed), and a free answer ("Autre réponse", or "En plus"
next to checkboxes; typing it picks it). The turn waits in `can_use_tool` until
"Répondre"; the answers go back as Claude Code expects them (checked against
2.1.283: a string per question, by its text, the labels joined by ", ", a free
answer as typed), and show in the transcript as the person's. "Arrêter" drops
the question. Also: the agent's text is rendered as Markdown (markdown-it, raw
HTML left as text), tool failures after a stop are no longer shown ("Arrêté"
says it), and studioz's static files are served `no-cache` (revalidated with
their ETag), since a browser kept a stylesheet older than the page. Tried on
slides: a two-question form (one single, one multiple choice with a free
answer) answered from the page, the agent repeating the answers; a question
stopped. Left: a question pending when studioz stops is lost (the turn with
it): `defer` and answering on resume, with phase 4's workflows.

**Increment 3: done** (2026-10-10): checkpoints and "Annuler ce tour".
`studioz.checkpoints` snapshots the workspace's files before and after each
turn (`git add -A` into a private index, `.run/studioz/agent/index`, copied
from the workspace's the first time; the workspace's index, HEAD and branch
never move), and keeps a turn that changed files as two trees under
`refs/studioz/<workspace>/{avant,apres}` plus `turn.json`. The transcript
lists the files each turn changed. "Annuler ce tour" (a second click
confirms) puts back the files still as the turn left them, deletes those it
created, and leaves one the person changed since (said in the transcript); it
is refused once the workspace's HEAD moved (a commit, a sync). The agent is
told with the next message which files went back. Only the last turn can be
undone, also after a studioz restart. Measured on slides: a snapshot takes
70 ms. Tried on `studioz-dev` (through the routes the panel uses: the browser
extension wasn't connected): the agent added a line to `eni/ml1/deck.yml`,
the turn listed it, the undo put it back (`git status` clean, refs removed),
and the agent, asked next, knew the file was back. Left: undoing more than the
last turn; the `refs/studioz/` of a closed workspace stay (harmless, a few
objects); the button itself not yet tried in a browser.

**Increment 4: done** (2026-10-10): usage and limit pauses. The panel's header
shows the account's windows as Claude Code reports them in each
`RateLimitEvent` (`raw.unifiedWindows`, checked with 2.1.283: « 5 h : 14 % · 7 j
: 77 % », in red from 75 %, the reset times in its tooltip; they count every
use of the account, not only studioz's). Each turn ends with its estimated
usage (`total_cost_usd`, at API prices: what it took from the subscription,
not a bill). A turn a limit stops (`status: rejected`) ends as "Interrompu par
la limite", and the conversation pauses: it resumes by itself at the reset
time (the reaper, every 5 s), telling the agent to carry on; "Annuler la
reprise" cancels it, a message from the person replaces it. Tried on slides:
a one-word turn on the long trial conversation showed 0,32 $ (the resumed
context), the header 14 % and 77 %. A real limit wasn't hit (tested with
fakes). Left: a pause doesn't survive a studioz restart; no warning before a
long task when a window is nearly full.

**Increment 5: done** (2026-10-10): the agent in the dialogs. The Commit
dialog has "Proposer un message" (`studioz.asks.draft_message`: one exchange
with no tool, on the diff of the files ticked and the last commits' subjects,
with Haiku to spare the plan; the person edits it), "Traduire avec l'agent"
beside each file changed without its other language, and "Demander à l'agent
de corriger" under a refusal; the Synchronisation dialog has "Demander à
l'agent de résoudre" on a conflict. Each sends the conversation a prompt
studioz writes from what the dialog shows (`asks.prompt`), closes the dialog
and opens the panel; the person checks the turn, then commits or continues
from the dialog as before. The editor's "Demander à l'agent" starts a message
about the passage under the cursor (file, line, selection): comments on
frames as instructions. It exposed a fault in increment 3: undoing used `git
restore`, which takes the workspace's own index lock, busy when studioz's
`git status` runs right after a turn; files are now written from the
snapshot's objects. Errors in the panel get their own line (the state's
updates rewrote the status). Tried on slides (`studioz-dev`): a French list
item added, the proposed message « Add Visualisation to big-data tools »;
"Traduire avec l'agent" closed the dialog, the agent followed the
repository's `sync-langs` skill and added « Visualizing » (39 s), and "Annuler
ce tour" put the English file back. The conflict and refusal buttons are
tested with fakes, not tried on a real conflict.

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
