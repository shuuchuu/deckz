# studioz plan: a UI for operating a deckz repo, agents included

## Where things stand, and how to resume (2026-10-23)

**Done:** phases 0, 1 and 2 (workspaces without agents: increments 1 to 8 under
"Phase 2"), and phase 3 (the agent in a workspace: increments 1 to 5 under
"Phase 3"), which the user then tried on real work, satisfied; and phase 4
(workflows: increments 1 to 5 under "Phase 4"), done overnight on 2026-10-11
while the user slept, not yet tried by them; then "Rien à porter…" on the
translation backlog (2026-10-11, after phase 4); then the VS Code layout's
increments 1 to 4 (2026-10-15, under "The VS Code layout"). All of it is pushed and
released (deckz 31.3.4). Phase 5 (long jobs) was planned on 2026-10-17 (under
"Phase 5"); its increments 1 (notifications, jobs kept across restarts, every deck's
build), 2 (videos), 3 (labs previewed), 4 (`deckz labs gpu pass`) and 5 (GPU passes
from studioz) are done: phase 5 is done. Then the memory guard "Risks" promised
(2026-10-18, under "Machine load"), the `jinja-syntax` check and the Commit dialog's kept draft ("Open items").
Phase 6 (the agent's usage) was planned on 2026-10-21 from the colleague's first
afternoon; its increments 1 (the model), 2 (a new conversation for a new file), 3
(the context's size) and 4 (slides' `docs/figures.md`, in slides' main as `b83c29fb`)
are done. Phase 7's increments 1 (logging in, and errors naming their fix), 2
(links in new tabs), 3 (the slide in view) and 4 (the PDF's outline) are done.
**Next:** phase 8 (planned 2026-10-23 after a publish from a stale workspace
rolled the labs back, its decisions taken the same day; its 5 increments done,
what's left is in each one's **Left**), phase 7's "Also left" (start with "Starting phase 7" below), phase 6's
increment 5
(the colleague's next afternoon measured), "Then, with the colleague" (below
phase 5), and the open items. A GPU pass rents a machine that costs money: never
start one without the user saying so. `git log
origin/main..main` in
`../deckz`, and in `../slides` for its `uv.lock`, lists what isn't pushed. Push and
release are the user's call.

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
| `problems.py`, `changes.py` | the panel's Problèmes tab and the sidebar's Changes panel; `changes.LangPairs` caches deckz's fr/en pairs |
| `baselines.py`, `comparison.py` | handouts as of the last commit, frame-by-frame before/after |
| `commits.py`, `sync.py` | the Commit and Synchronisation dialogs |
| `memory.py` | the machine's available memory (`/proc/meminfo`): the status bar's item, and the threshold under which builds and renders wait |
| `jobs.py`, `actions.py` | the job queue, kept in each workspace's `.run/studioz/jobs/`; build (a deck, every deck), upload, publish |
| `videos.py` | the Vidéos view and a scene's page: `deckz videos list --json`, the renders of the last commit kept (hard links) for the before/after, the render jobs |
| `gpu.py` | GPU passes: the modal's estimate (`deckz labs gpu pass --dry-run --json`), the pass's and `down`'s job steps, the machines billing (`status --plain --offline`, cached by their `state.json`) |
| `labs.py`, `notebooks.py` | the TP view and a notebook's page (`deckz labs list --json`, cached while the notebook files are the same); a notebook rendered as Colab shows it, and compared cell by cell, in a sandboxed frame |
| `agent.py` | each workspace's agent conversation (Agent SDK): options, the git refusal hook, questions, the transcript |
| `checkpoints.py` | the workspace's files before and after each agent turn, and undoing the last one |
| `asks.py` | what the dialogs ask the agent (prompts), and the proposed commit message |
| `workflows.py` | the workflows a workspace's `deckz.yml` declares (`studioz.workflows`), their forms' prompts and files |
| `static/` | `deck.js` (pdf.js viewer, comparison, the slide in view, the Plan), `video.js` (a scene's page: before/after played together), `lab.js` and `notebook.js`/`notebook.css` (a notebook's page, and the sandboxed page inside its frame, MathJax's configuration), `editor.js` (CodeMirror: Markdown, YAML, Python), `dialogs.js` (dialogs opened from reloading panels), `agent.js` (the agent panel), `layout.js` (the VS Code layout: activity bar, sidebars, bottom panel, sashes, status bar), `notifications.js` (jobs' ends: toasts, the bell, desktop notifications), vendored JS (`uv run doit vendor`) |

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
  recreated clean at `3fbcc34e` on 2026-10-15, the previous one gone: create it
  again from the home page if it's gone); the Fortinet deck
  (`decks/orsys/INTRA/2026-10-fortinet` since slides moved its decks under `decks/`)
  is the usual test deck. Leave it clean: a scratch
  commit comes back off with `git reset --soft 3fbcc34e && git reset -q` (or the new
  base after an update), and files are restored from a copy taken first. Restart
  the server after changing Python code: the templates are read fresh, the modules
  not, so a page may call what the running code lacks.
- A workspace runs its own deckz, installed from `../deckz` (main). To try deckz
  changes from the worktree, point the workspace at it for the trial:
  `.venv/lib/python3.12/site-packages/deckz.pth` holds
  `/home/mog/repos/shuuchuu/deckz/src`; write
  `/home/mog/repos/shuuchuu/deckz-studioz/src` there, and put it back after.
- Never click "Publier" (labs, videos, or Sync's push) nor "Envoyer" on slides: they
  publish to trainees, slides' origin or Google Drive. The tests cover them with
  fakes; on slides, stop at the confirmation.
- The browser (Claude in Chrome) needs Claude Code started with `claude --chrome`.
  The sidebar's panels reload themselves, so an element found then clicked a
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

- ~~A broken Jinja tag (`{{ x`) passes `deckz check`~~ Done 2026-10-18: deckz's
  `jinja-syntax` check parses every content file (shared and deck-local) with the
  repository's own Jinja environment and checks its filter and test names (parsing,
  not compiling: 1,558 files of slides in 0.4 s, plus 1 s listing the decks'
  directories, which `raw-latex` pays too); a problem names the file, the line and
  the fix (`{% raw %}` for braces meant as text). Slides passes it as it is. Tried on
  `studioz-dev`: a `}}` removed, `deckz check` and `--staged` (the pre-commit hook)
  refused it, studioz's Problèmes showed it, and its link on a deck page opened the
  editor on the line; put back, the problem went within 28 s. Found on the way:
  `deckz status` keeps 15 check problems, in check order, so 123 old `lab-format`
  ones hid the new one; the problems naming a file of your changes now come first.
- `tests/test_deck_builder.py::test_interrupt_does_not_wait_for_running_compilations`
  failed once in about 20 full runs, under load: a timing test (a 0.5 s sleep),
  not looked into yet. (`test_labs_gpu.py::test_queue_kills_what_a_run_leaves_running`
  failed the same way: it checked a process gone right after `kill -9`, which
  returns before the process exits; it now waits.)
- deckz's messages are in English in a French UI; the lab checks read every notebook
  again each (6 of `deckz status`'s 10 s on slides).
- ~~The Commit dialog's draft is lost when the page changes.~~ Done 2026-10-18: the
  dialog keeps its draft (message, files chosen, the `Lang-sync` answer and reason)
  in the workspace's `.run/studioz/commit-draft.json` as the person types (half a
  second after), ticks a file or the proposed message arrives; a dialog opened afresh,
  on any page, after a restart or in another tab, starts from it (a file changed
  since chosen by default, as before); a commit clears the message, Fermer keeps it.
  Tried in Chrome on `studioz-dev`: a message typed on the Fortinet deck's page came
  back on the workspace page, and a file unticked stayed so across a reload.
- The untracked `.claude/` in `../deckz` is the frontend plugin's install: the
  user's, kept, never committed.
- slides depends on studioz (editable): a new studioz dependency makes slides'
  `uv.lock` stale, and the next `uv run` there rewrites it. Merge such a change
  with a `uv lock` committed in slides at once (as `1cf2de1d` did for
  `claude-agent-sdk`); each workspace's own `uv.lock` follows when it syncs.
- The agent sometimes writes its commands' descriptions in English, although the
  appended prompt asks for French (later turns were in French); a command failing
  for an ordinary reason (`grep` finding nothing, exit 1) shows as "Refusé ou en
  échec".
- `test_interrupt_does_not_wait_for_running_compilations` (above) failed a
  second time during phase 3, in the pre-commit hook; it passes alone. On
  2026-10-15 it failed again in the hook, with `test_cli_typst.py::
  test_ctrl_c_stops_the_build_at_once` (its build not stopped within 20 s): both
  passed alone and on the next run.
- A limit pause doesn't survive a studioz restart (a pending question now
  does); no warning before a long task when a usage window is nearly full.
- deckz's Drive links (`a9e824c`, `8254236`, from a slides session, 2026-10-23):
  `deckz upload --dry-run --json` adds `unlinked` (a PDF with no link in the deck's
  registry, `paths.drive_links`: `<user config dir>/drive-links/<deck path>.yml`, the
  person's own, not committed) and `unbuilt` (a reserved PDF not built), both refused
  like `outdated`. studioz's upload dialog (`actions.upload_plan`) reads `pdfs` and
  `outdated` only: for a deck with a registry (`deckz upload --reserve`), the job
  fails on deckz's refusal instead of the dialog saying so first. Show them as
  `outdated` is.

### Starting phase 7

Read phase 7 (below phase 6), then "Developing and trying a change" above. The user
runs studioz one increment at a time: each one coded and tested in the worktree
`../deckz-studioz` (branch `studioz`; `git merge --ff-only main` there first, since
`../deckz` may have moved), `uv run doit check test`, tried for real on slides'
`studioz-dev` (headless Chromium through the Playwright in deckz's `.venv`, run with
`python -I`, when the Chrome extension isn't connected), its entry written in this
plan with what was measured and what's left, the resume section above and deckz's
`CLAUDE.md` studioz paragraph updated, committed in the worktree, `ListAgents`
checked for slides sessions (tell them only of a change in what deckz does), and
`../deckz` fast-forwarded (`git merge --ff-only studioz`). The user pushes. The
pre-commit hook's two Ctrl-C timing tests fail about one run in three: retry the
commit ("Also left" has their fix).

Increments 1 to 4 are done (their entries under phase 7); next is its "Also left",
the flaky timing tests first (one failed again during increment 4, in a full run).
Logging in on a scratch
`CLAUDE_CONFIG_DIR` (empty) never touches the person's own login; a model that
doesn't exist (`studioz --model claude-nonexistent-9`) and a bogus session id in a
workspace's `.run/studioz/agent/session` give real errors at no cost.

### Starting phase 4

Read "Workflows" (the `deckz.yml` declaration sketched), "Agent configuration"
(the `defer` findings), "What a non-expert can expect", and phase 3's
increments below: the agent's conversation (`studioz.agent`), its questions,
checkpoints, usage and the dialogs' asks (`studioz.asks`) are what workflows
build on. slides' skills are `nouvelle-formation`, `nouvelle-section`,
`qa-formation`, `qa-fix`, `sync-langs`, `markdown-edge-cases`
(`../slides/.claude/skills/`). A suggested order, each a usable increment:

1. **Workflows declared**: done (see "Phase 4").
2. **Opening a workspace from a workflow**: done (see "Phase 4").
3. **Questions answered later** (`defer`): done (see "Phase 4").
4. **QA → fix**: done (see "Phase 4").
5. **The translation backlog**: done (see "Phase 4").

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

The operability plan (`plans/operability.md`) made shuuchuu/slides runnable without an
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

**Increment 1: done** (2026-10-10): workflows declared. A workspace's own
`deckz.yml` declares them under `studioz.workflows` (studioz's README,
"Workflows", is the reference): a name, an optional description, the skill, a
`scope` (`workspace`, or `deck` for one deck, `{deck}` in the prompt), inputs
(`text`, `long-text`, `file`, required unless said) and the prompt. The
workspace page lists them all ("Avec l'agent"), a deck page behind "Avec
l'agent…" (its deck's first, about the deck on screen); each opens a form
(the deck chosen when it isn't on screen, "Ce que l'agent recevra" showing
the prompt with the fields' labels), whose "Commencer" sends the
conversation the prompt filled in, preceded by "Suis la skill `<skill>` du
dépôt", while the transcript shows the workflow's name and the prompt; the
dialog closes and the agent's panel opens. A file is kept under
`.run/studioz/fichiers/` (the same file given again is kept once). With a
conversation going on, a box offers to start a new one. The section's schema
refuses unknown keys, a prompt field no input fills and duplicate names,
shown in place of the list with each problem's path; a workflow whose skill
the workspace lacks is shown so, and refused. deckz ignoring the section is
now a deckz test (pydantic's default, `extra="ignore"`). Tried on slides
(`studioz-dev`, recreated from the home page), with four workflows declared in
its `deckz.yml` for the trial (uncommitted, put back): "Synchroniser fr/en"
from the Fortinet deck's page loaded the `sync-langs` skill as the turn's
first tool and found nothing to translate (42 s, 0,34 $ estimated);
"Nouvelle formation" with a Markdown program and a new conversation kept the
file, loaded `nouvelle-formation`, which read it and asked its two questions
as a form (stopped there); a misspelled key showed its two errors on the
workspace page. The user approved those four for slides: committed as
`7bd8a6f9` in the workspace `studioz-workflows` (`../slides--studioz-workflows`),
for the user to sync from studioz. Left: the home page's workflows
(increment 2), and `qa-fix` after a QA (increment 4).

**Increment 2: done** (2026-10-10): opening a workspace from a workflow. The
home page lists, under "Commencer avec l'agent", the workflows of the main
checkout's `HEAD` (read through git, `workflows.declared_at`, so another
session's uncommitted edits there don't count: a new workspace starts from
that commit), each opening its form with the workspace's name (optional:
otherwise after the deck, or the workflow, numbered when taken), and the
decks of that commit for a deck's workflow. "Commencer" checks the answers
and the login first, then creates the workspace as "Nouvel espace de
travail" does, keeps its files there and starts the workflow, and opens the
workspace (a deck's page for a deck's workflow) with the agent's panel
unfolded (`?agent`). If `deckz setup` left something missing, the workflow
doesn't start and the page says so with the setup's findings. Tried on a
throwaway local clone of slides at `7bd8a6f9` (slides' main checkout doesn't
declare workflows until the user syncs that commit; the clone was seeded from
slides' builds, set up, then deleted with its workspace): "Synchroniser
fr/en…" on the Fortinet deck created `2026-10-fortinet` and showed its deck
page with the agent at work 9 s after "Commencer"; the turn loaded
`sync-langs` and found nothing to translate (59 s, 0,36 $ estimated). Left:
nothing for this increment.

**Increment 3: done** (2026-10-11): questions answered later. A
`PreToolUse` hook defers every `AskUserQuestion`: the turn ends on the
question (no "Terminé"), which studioz keeps in
`.run/studioz/agent/question.json` and shows as before; the Claude Code
process stops at once (about 0.5 GB freed while the person thinks). Answering
resumes the session in a new process with a short note
(`agent.ANSWERED`); Claude Code first runs the pending call again, which
reaches `can_use_tool` (not the hook), answered from the file. Checked first
with the pinned SDK (a Haiku experiment in the scratchpad, a few cents): the
deferral and the resume work across processes, but a client still connected
doesn't resume the call on its next message (the model asks again), hence
the disconnection. A message written instead of answering, or "Écarter la
question" (the stop button's label then), declines it: the resumed call is
refused with that reason. "Nouvelle conversation" forgets it. A question made
alongside other tool calls can't be deferred (documented): it waits live, as
before, and is lost if studioz stops. Tried on slides (`studioz-dev`): the
agent asked "Thé ou café ?", the turn ended with no Claude Code process left,
studioz was restarted, the form was back with its new hint, and "Café" made
the agent answer « Café. » 6 s later (0,19 $ estimated for both turns, the
resumed context). Left: a limit pause still doesn't survive a restart.

**Increment 4: done** (2026-10-11): QA → fix, generically. A workflow may
declare `report: true`: studioz appends to its prompt where and how to write
its findings (a Markdown task list in `.run/studioz/rapports/<workflow>--<deck>.md`,
`## ` per category, `- [ ] ` per self-contained finding: the format is
studioz's, since it reads it back, the content stays the skill's, so neither
`qa-formation` nor `qa-fix` changed). The navigator's "Rapports" panel lists
the reports (written or awaited, how many ticked) and opens each as a
checklist under its headings, each tick written back into the file; `then`
(a name, skill, prompt and description, its prompt getting `{chosen}`,
`{report}` and `{deck}`) is the button under it, sending the findings ticked
to the conversation. A new run on the same deck removes the previous report.
slides' QA workflow declares it (`ce4b0a69`, in the workspace
`studioz-workflows` with `7bd8a6f9`; it needs this deckz, whose schema refuses
keys it doesn't know). Tried on slides (`studioz-dev`, the declaration copied
for the trial), kept cheap since the week's window stood at 81 %: the QA of
the Fortinet deck limited by its "points à regarder" field to the deck's own
`content/about/` and no subagent (62 s, 0,51 $ estimated) wrote a clean
checklist of 5 findings under the skill's categories; the dialog showed it,
a tick reached the file, and "Appliquer les corrections" started `qa-fix` with
that finding (stopped after 7 s, nothing changed). Not measured: a full QA's
usage (still to do on a real one). Left: nothing for this increment.

**Increment 5: done** (2026-10-11): the translation backlog. deckz: `deckz
i18n stale --json` (`{"stale": [{path, sibling, since, commits}]}`).
studioz: `studioz.backlog` runs the workspace's own one in the background,
again when its HEAD moves (2.2 s on slides), for the navigator's "À
traduire" panel (hidden when empty): each file, its other-language sibling
and the commits not followed (their subjects in a tooltip), with "Traduire
avec l'agent" sending the conversation a prompt (`asks`'s `rattraper`: the
commits, the `git diff` since the sibling's last change, read the sibling as
it is). The Commit dialog presets "rien à traduire" with the reason "portage
de <file>" when every one-sided file chosen is a backlog entry's sibling,
since the commit-msg hook asks a trailer of such a port. Tried on slides
(`studioz-dev`, pointed at the worktree's deckz for `--json`, then put back):
the panel showed slides' one entry 2.7 s after the page opened; the agent
read the diff and found nothing to port (French typography, a case fix: 14 s,
0,22 $ estimated), which exposed the gap under "Open items"; with a scratch
edit of the English file, the Commit dialog came preset. Left: that gap.

**Phase 4 is done.** Not tried by the user yet: the four workflows on slides
(once synced), a full QA and its fixes, a question answered after a
restart, the backlog panel.

**After phase 4: nothing to port** (2026-10-11), the gap increment 5 left: a
backlog entry whose changes need nothing in the other language, committed
without its `Lang-sync: fr-only` trailer, couldn't leave the list. deckz: a
`Lang-synced: <path>` trailer (either side of the pair, repeatable) makes its
commit the pair's sync point in `deckz i18n stale`'s walk, both ways, like a
per-pair `i18n.synced_at`; `deckz i18n mark-synced PATHS... --reason TEXT`
writes it in an empty commit (`git commit --allow-empty --only --no-verify`:
nothing staged goes in, and there's no file for the hooks to check), refusing
a path the backlog doesn't list or an empty reason; `deckz i18n stale` and
`deckz status` name it as the fix. The commit-msg rule is unchanged (a
one-sided commit still needs `Lang-sync`). studioz: "Rien à porter…" beside
"Traduire avec l'agent" opens a dialog (the commits, a reason) running the
workspace's own `deckz i18n mark-synced`; the decks' baselines carry over to
the new commit (`baselines.carry_over`: same files, nothing rebuilt); the
agent's hook refuses `deckz i18n mark-synced` (it commits) and the catch-up
prompt asks it to say why when there's nothing to port. Tried on slides
(`studioz-dev`, pointed at the worktree's deckz, over HTTP: the browser
extension wasn't connected): the real entry, an empty reason refused, the
commit (empty, its trailer), the panel then empty, `deckz i18n stale` and
`deckz status` clean, `deckz hooks check-commits` passing, a second mark
refused; the commit then taken off and the baselines put back. Then, at the
user's request, slides' entry closed for real on its main (`4aa7e1be`) and
`sync-langs` taught the command (`25d74f24`), neither pushed.

### The VS Code layout (2026-10-15)

The user, trying studioz: too many panels side by side (navigator, PDF, editor,
agent), and responsive bugs (the editor's file path, wrapped at every character, grew
into a tall column once the agent was open). Asked for a pass towards VS Code's
layout; agreed plan, each a usable increment:

1. **The shell**: done (below).
2. **A bottom panel** (Ctrl+J) with tabs: Problèmes (out of the sidebar, where its
   text and fixes get the width), Construction (the build failure and its log
   lines, instead of the red banner pushing the PDF down), Tâches (the jobs' logs,
   now a dialog behind the status bar's item). It opens by itself on a build
   failure.
3. **Editor groups**: the PDF and the editor resizable against each other (a sash),
   the split already flipping to one above the other when narrow.
4. **A command palette** (Ctrl+Maj+P: build, upload, commit, sync, the workflows)
   and a quick "open deck" (Ctrl+P), which would also slim the deck's toolbar.

The agent stays on the right, as VS Code's chat does: the user agreed, Ctrl+B
hiding the left sidebar being enough room.

**Increment 1: done** (2026-10-15): the shell. A workspace's pages
(`workspace_base.html`, `layout.js`) are an activity bar choosing the sidebar's one
view (Formations, Modifications with sync and À traduire, Problèmes, Publication,
Avec l'agent with the workflows and Rapports), each icon's badge the count its panel
shows; the page; the agent on the right; resizable sashes (double-click: default
width), Ctrl+B and Ctrl+Alt+B (also the title bar's two toggles), all kept per
browser and applied by an inline script before the first paint; and a status bar
(branch with ↓/↑ from the Synchronisation panel, problem count, the build state,
page, jobs, the agent's state) whose items open their view. Along the way, from the
user during the trial (and, found in increment 2, a bug: a text substitution had
put the deck tree's script inside `showSidebar`, so its filter and remembered folders
worked only after the sidebar was toggled; the trial never typed in the filter):
- the deck and file paths are one line, their folder shortened first (an ellipsis),
  the name whole; the editor's "Enregistré"/"Enregistrer" became VS Code's dot,
  shown while the file has unsaved changes (a click or Ctrl+S saves);
- Formations is a tree (`workspaces.deck_tree`, nested `<details>`): the folders
  every deck shares (slides' `decks/`) left out and shown beside the title, a folder
  holding only one folder merged with it (`orsys/INTRA`, VS Code's compact folders),
  the current deck's folders open, the ones opened kept per browser, the filter
  opening the folders of the decks it matches. Automatic rather than a setting:
  nothing to configure, and it follows a reorganisation;
- Publication replaces the title bar's "Publier…": the labs' and videos' state from
  `deckz status` (à publier, with what; à jour), each button opening the existing
  publish dialog, which stays the confirmation (one click in a sidebar is too easy
  for what reaches trainees).
The PDF and the editor go one above the other when the page is narrower than 760 px
(a container query). The dialogs moved out of the sidebar into the page. Two
class collisions found: the home page's `.page` (`max-width: 72rem`, padding) also
styled pdf.js's pages, capping wide pages at 1152 px while their text layer kept
the right width (a horizontal scrollbar with the sidebars hidden): now `.home`;
pdf.js's stylesheet styles `.sidebar`, hence `.primary-sidebar`. Tried on
`studioz-dev` in Chrome (1920 px wide, and narrow by widening both sidebars:
stacked editor, one-line path), stopping at the publish dialog. **Left:** a deck's
labs waiting to be published show in both Problèmes and Publication; the deck tree
has no keyboard navigation; the workspace page's own workflows list now duplicates
the Avec l'agent view.

**Increment 2: done** (2026-10-15): the bottom panel, under the page only (the
sidebars run the whole height, as in VS Code), shown by Ctrl+J, the title bar's
middle toggle or a status bar item (which toggles its own tab), resizable, its tab,
height and visibility kept per browser, hidden at first. Tabs: **Problèmes** (out
of the sidebar, its fixes beside each problem), **Construction** on a deck page (the
build's state in a sentence and deckz's error lines instead of the red banner; the
`file:line` deckz names first is a link to the editor; a red dot on the tab; the
panel opens on it when a build fails, as VS Code shows a failing task's output), and
**Tâches** (the jobs' list and logs, the dialog the status bar opened before gone).
A job started from a dialog (build, upload, publish) answers with
`HX-Trigger-After-Settle: jobs-changed, job-started`: the page closes the dialog
showing it and opens Tâches; after settling, and found by its content, since the
form that sent the request is no longer in the page by then. `GET /taches` is now
the tab's content. Found: the deck tree's `li.deck` took the deck page's `.deck`
(`display: flex`) over `hidden`, so the filter hid nothing on deck pages: now
`li.deck-item`, and `[hidden]` wins over any class (`!important`), this being the
third collision. Tried on `studioz-dev` (Chrome): Ctrl+J (Chrome lets the page have
it), a broken Jinja tag written in a content file (a copy kept, then put back)
opening Construction, its link opening the editor on line 28, the build back to "À
jour" with the panel left open, a handout build started from Construire (the dialog
closed, Tâches showing its log), the filter, the sash. **Left:** the before/after
view and the agent's own errors could use the panel too; no maximise button; the
Tâches log isn't kept scrolled to its end as it grows.

**Increment 3: done** (2026-10-15): the PDF and the editor share the page by a
sash, as a ratio (`--split`, the PDF's share, between 15 % and 85 %), so that it
holds when the sidebars, the panel or the window change, side by side or one above
the other (the container query of increment 1 flips the sash's direction too);
double-click for half and half; kept per browser and applied before the first
paint. Every sash's grab area is now 3 px wider on each side than its line: the
first try at dragging the 5 px line missed it. Tried on `studioz-dev` (Chrome):
side by side to 29 %, stacked (sidebars widened), the reset, the sash gone with the
editor. **Left:** one ratio for both directions; no way to put the editor on the
left, nor to stack them by choice when wide.

**Increment 4: done** (2026-10-15): the palette, as VS Code's (`palette.js`).
Ctrl+P, or the title bar's "Rechercher…", lists the decks (from the sidebar's tree,
without the folders they all share); ">" first, Ctrl+Maj+P or F1 lists the commands:
build, upload, the before/after view, the other language, commit, sync, publish,
each declared workflow, writing to the agent, every view and tab, home. Matching
ignores case and accents and takes a substring first, then the letters in order
("eurnxt" finds `2025-11-euronext`). A command is a hidden button
(`_commands.html`) carrying what the page's own buttons carry (`data-dialog`,
`data-toggle`, `data-show-view`, the new `data-open-panel`, which shows a tab
whatever is shown); running it clicks it, so no action is written twice;
`data-click` clicks another element, `data-focus` focuses one. Chrome leaves
Ctrl+P (print) and F1 to the page. The deck toolbar's buttons stay, the palette
being for who knows it. Found: since increment 3, with the editor closed, the PDF
took only half the width (a flex grow factor under 1 takes only that share of the
free space; increment 3's check ran stacked, where it doesn't show); and the
language links' `href` become absolute once the view switches (`deck.js`), so
commands find them by `data-lang`. Tried on `studioz-dev` (Chrome): Ctrl+P, Ctrl+Maj+P,
F1, building's dialog, the QA workflow's form (closed, not started), Problèmes,
the agent's box focused, avant/après, the switch to English, opening another deck.
Switching to English for the first time stalled the tab's script runner 45 s while
its first English build ran, then all was well: not looked into. **Left:**
Firefox keeps Ctrl+Maj+P (private window), so there it's F1 or ">"; no recent decks
or files first; content files aren't in Ctrl+P.

### Phase 5: long jobs and the remaining previews (planned 2026-10-17)

Labs on GPU (notebook previews and diffs), Manim drafts and full renders, `deckz run
decks`, through the queue, with notifications when they end. Read "Previews" (the
labs and videos rows), "Agent configuration" (the job queue) and phase 2's increment
8 (`studioz.jobs`, `studioz.actions`) first.

**What deckz offers today.** A GPU pass takes six commands: `deckz labs gpu up`,
`queue <notebooks>` (`--short` for a `SHORT_RUN`), `run`, `status --watch` (which
fetches and notes each finished run), `fetch`, and `down`. After those, each demo
needs its own `deckz labs outputs <executed> <notebook>` to keep its outputs. `up`
rents the cheapest offer of `labs.gpu.gpus` on Vast.ai and logs its price per hour,
and the machine bills until `down`. Nothing estimates a pass's cost beforehand, and
nothing destroys the machine if the session running the pass dies.
Videos: `deckz videos list` shows each scene's state, and `deckz videos render
[scene] --quality l…k` renders it. A draft (`l`) replaces the scene's render file,
and `deckz videos publish` refuses a render that isn't at `videos.published_quality`,
so a draft can't be published by mistake; publishing that scene needs a full render
again.

**Confirming what costs money.** VS Code asks before a costly or irreversible action
with a modal dialog (`showWarningMessage` with `modal: true`): a message, a detail,
and a primary button that names the action, beside Cancel. studioz does the same
(agreed with the user, 2026-10-17). "Exécuter sur GPU…" opens a modal that gives:
- the notebooks;
- the GPU and its current price per hour (from deckz's dry run, increment 4);
- the estimated duration, when earlier runs of these notebooks give one;
- the ceiling after which deckz stops the pass;
- that the machine is destroyed at the end.

Its button names the action and the estimate ("Louer une T4 et exécuter (≈ 0,40
$)"). The focus is on Annuler, so Enter rents nothing, and there is no "ne plus
demander" box. Two other VS Code habits go with the modal:
- a status bar item, like VS Code's remote indicator, shown while a machine bills,
  with the GPU, the time and the cost so far; a click opens the pass's log with
  "Arrêter la machine";
- a notification when the pass ends.

The agent can't start a pass: studioz's agent hook refuses `deckz labs gpu up|run|
pass`, as it refuses commits. When the agent thinks a pass would help, it says so,
and the person starts it from the modal. This refusal belongs to studioz, not to
deckz's `bash_denial`, because terminal sessions run passes on purpose.

Each increment is usable on its own:

1. **Notifications, and jobs that outlive a restart.** The notifications work as VS
   Code's do:
   - a toast at the bottom right when a job ends (done, failed with its last error
     line, or stopped), whose "Voir le journal" opens Tâches;
   - the status bar's bell, keeping the last ones;
   - a desktop notification (the Notification API, permission asked on first use)
     when the tab is hidden.

   Each job's record and log go to `.run/studioz/jobs/`. After a restart, the
   finished jobs are still listed, and a job that was running shows as
   "interrompue", with "Relancer". `deckz run decks` (every deck of the workspace,
   every output spelled out) becomes a job, started from the palette and from the
   Formations view's title.
2. **Videos.**
   - A Vidéos view in the activity bar, from `deckz videos list` (à jour, à rendre,
     jamais rendue).
   - A scene's page: its last render in a `<video>`, and its source (the scene's
     module) in the editor beside it.
   - "Brouillon" (`--quality l`, a job of a few minutes) and "Rendu final" (at
     `videos.published_quality`), each a job that notifies when it ends.
   - Before/after: the render at the last commit beside the new one.
   - The Publication view names the scenes that are only drafts, since deckz will
     refuse to publish them.
3. **Labs previewed.**
   - A TP view listing the labs and each notebook's kind and language (if no deckz
     command lists them, add `--json` to one).
   - A notebook's page showing it rendered as Colab shows it, outputs included
     (nbconvert's HTML). It isn't edited in CodeMirror (it's JSON): the agent or
     "Ouvrir dans mon éditeur" edits it.
   - Before/after since the last commit, cell by cell with outputs (nbdime, or what
     `deckz.labs.comparison` already does; check first).
   - The labs' problems already in Problèmes link to the notebook's page.

   nbconvert or nbdime would be a new studioz dependency: re-lock slides along with
   it (see "Open items").
4. **One command for a GPU pass, in deckz.** By the operability guidelines, six
   commands to remember make a missing command. `deckz labs gpu pass <notebooks>`
   (name to settle) does `up`, `queue`, `run`, the following, the fetching and the
   noting, and then always `down`: on success, on failure, and on SIGINT or SIGTERM
   (what studioz's Arrêter and its own shutdown send). Its options:
   - `--max-hours`, the ceiling: past it, the run is killed and the machine
     destroyed;
   - `--write-outputs`, off by default since it overwrites: writes each demo's
     outputs back into its notebook when its run exited 0, as `labs outputs` does;
   - `--dry-run --json`: the offer it would rent now (GPU, $/h), the notebooks, and
     each one's last known run time (from the machines' `notes.md`), for the
     modal's estimate.

   `deckz labs gpu status --plain` also gains each machine's price and start time,
   for the status bar item. A person in a terminal gets the same safety. It needs
   its docs page, its place in `--help`, and tests with the fake backend.
5. **GPU passes from studioz.**
   - "Exécuter sur GPU…" on a demo's page and on a selection in the TP view (full or
     short run), opening the modal above.
   - The pass runs as a job, `--write-outputs` and the ceiling spelled out.
   - The status bar item shows while a machine bills. After a restart, studioz finds
     the machine again through `deckz labs gpu status`, even one a crash left
     running.
   - "Arrêter la machine" runs `deckz labs gpu down`, and asks first only while a run
     is in progress, which would be lost.
   - The notification at the end opens the notebook's before/after.

   The tests run against a fake deckz. On slides, a real pass happens only once the
   user says so: the shortest demo, in short mode, with its estimate shown to them
   first.

**Increment 1: done** (2026-10-17). Jobs are kept in their workspace's
`.run/studioz/jobs/` (`<id>.json`, the record; `<id>.log`, appended line by line), the
last 30 per workspace, loaded the first time studioz looks at a workspace, their
numbers following on. When studioz stops, it stops its jobs (as before), now kept as
"interrompues" (`JobState.INTERRUPTED`), and so are those a crash left running or
queued. Relancer comes in two kinds: a build carries `rerun` and runs again as is
(`POST …/taches/{id}/relancer`; VS Code's "Relancer la tâche"); an upload or a
publication carries `form`, the dialog that starts it, and "Relancer…" opens that
dialog again, since what it sends may have changed since it was confirmed.
Notifications (`notifications.js`) come from the status bar's jobs item, which already
reloads every 3 s: its `data-ended` lists the last jobs ended (state, title, and for a
failure its last log line without deckz's time and level). Each is notified once per
browser (kept per workspace in `localStorage`; on a first visit, what ended before
isn't news):
- a toast at the bottom right whose "Voir le journal" opens Tâches; a success hides
  after 8 s (not while hovered), a failure stays until closed;
- the bell at the status bar's right end, with its unread count, opening the center
  (the last 20, "Tout effacer", Escape or a click outside closes it); opening it reads
  them and clears the toasts;
- a desktop notification when the page is hidden, once allowed from the center's
  "Notifications du bureau…" (a browser asks only after a click).

"Construire toutes les formations…" is the Formations view's title action (VS Code's
icons on a view's title) and a palette command: the build dialog without a deck, French
only by default (English stops at the first deck missing a translation), as `deckz run
decks`, every output spelled out, run in the workspace. Along the way, the Tâches log
now scrolls itself and follows its end as it grows, unless the person scrolled up in it
(the VS Code layout's increment 2 left that). Tried on `studioz-dev` with headless Chromium
(Playwright from deckz's `.venv`; the Chrome extension wasn't connected): the Fortinet
deck's handout build (toast, bell, hidden after 8 s); the same build failing on a broken
Jinja tag (copy kept, put back), whose toast stayed with deckz's error and whose desktop
notification went out while the page was hidden (a stubbed `Notification`); every
deck's build started (`deckz run decks --handout --no-presentation … --lang fr`), then
stopped (its toast); then studioz stopped with Ctrl-C during that build, started again:
the job "interrompue", no `deckz` left running, Relancer running it again. **Left:**
a toast covers the agent's send button while shown (as VS Code's cover the editor); a
job stopped while deckz is still importing logs a Python traceback (deckz's Ctrl-C);
several tabs of one workspace each show the toast; a crash (not a stop) leaves a step's
process running until its next log line finds the pipe closed.

Tried again in real Chrome (2026-10-17), on the Fortinet deck: the bell's
"Notifications du bureau…" opened Chrome's permission prompt, and once allowed the
button left the center. A build that ended while the tab was in the background gave a
real desktop notification (Chrome fired its `show` event; the user saw it, "informative").
The toasts and the center look right: a success hid itself after 8 s, a failure (a
broken Jinja tag, put back) stayed with deckz's error line. studioz stopped with Ctrl-C
during the deck's full build (fr and en): the job came back "interrompue" with a
toast, no `deckz` left, and Relancer built it again. **Found and fixed:** the Tâches
tab's count of running jobs stayed at 1 after the job ended, since only the job's own
section reloads then; its last reload now fires `jobs-changed`, which reloads the tab.
The extension can't put its tab in the background (no `visibilitychange`): the user
clicked another tab for the desktop notification's trial.

**Increment 2: done** (2026-10-17). In deckz: `deckz videos list` gains each render's
state as a last column (`missing`, `stale`, `draft`, `fresh`: `deckz.videos.state`,
which `out_of_date` now uses) and `--json` (the scene's module, its `class` line, the
sources its stamp covers, each render's language, file, poster, quality and state);
`deckz status` names each draft with the command rendering it at the published
quality, instead of counting them, so the Publication view names them; and a render
is moved into place (`utils.copy_file_if_changed`), never written over. In studioz
(`studioz.videos`):
- a Vidéos view in the activity bar: each scene by folder, its most pressing state
  (jamais rendue, à rendre, brouillon, à jour), the count of those not up to date;
- a scene's page (`/espaces/<name>/videos/<video>`): its render in a `<video>` (fr/en,
  one render for a scene without text), its module in the editor at its `class` line
  (CodeMirror gains Python; `studioz.sources` lets it edit `.py` under the scenes'
  directory only), "Brouillon" (`--quality l`, enabled only when a render is missing
  or stale: on an up-to-date render it would only replace a better one) and "Rendu
  final" (at `videos.published_quality`), each a job; both in the palette;
- "Avant/après": the render as of the last commit beside the current one, played,
  paused and seeked together. Renders aren't committed, so studioz keeps the last
  commit's: whenever it lists the videos, a render up to date with sources unchanged
  since the commit is the commit's, hard-linked under `.run/studioz/videos/<key>/`, the
  key naming the sources' blobs at `HEAD` (a commit leaving the scene alone keeps it).
  The link costs no space and survives the next render since deckz now replaces the
  file rather than writing into it. The files are served from the videos' directory
  and that one only (`/espaces/<name>/rendus/…`, with range requests).

studioz's `deckz status` runs again when a render's stamp or quality changes too (git
ignores renders): without it, the Publication view kept a draft that had since been
rendered final. Tried on `studioz-dev` in Chrome (the workspace's deckz pointed at the
worktree, the renders and scenes copied first and put back after, byte for byte):
gradient-descent's dot made bigger, the view and the page followed ("à rendre", the
editor reloading), "Brouillon" rendered it in 7 s (a 9 s scene), the before/after
showed both, played together; "Rendu final" (h, from the palette) took 24 s; the
Publication view named the draft 29 s after the click, and dropped it after the final
render. causal-mask in English, the view switched without reloading. The six other
kept renders became hard links (the first listing had copied 98 MB). **Left:** the
before has no poster (the poster is written over by ffmpeg, so not linked): both sides
show their first frame; a scene's page isn't in Ctrl+P; renders made while studioz
never saw the scene unchanged have no before (the page says so); `deckz videos render`
of a long scene in a job can't be told apart from a stuck one (Manim's progress isn't
in its log).

**Increment 3: done** (2026-10-17). In deckz: `deckz labs list [--json]`, each
notebook's lab, kind and language (and its file, in JSON), in the guide beside `labs
missing`. In studioz:
- a TP view in the activity bar (`studioz.labs`): the labs by folder, each with its
  kinds ("démo", "TP", a lone language named), those changed since the last commit
  marked, their count as the badge, and a filter (kept across the list's reloads);
- a notebook's page (`/espaces/<name>/tp/<lab>/<kind>?lang=`): the notebook rendered as
  Colab shows it, outputs included, its other language when one is missing (the page
  says so), "Ouvrir dans mon éditeur" (`xdg-open`/`open`: the system's application for
  notebooks), and the TP commands in the palette;
- "Avant/après": the notebook at `HEAD` beside the current one, cell by cell
  (`studioz.notebooks.compare`): cells matched by Colab's `metadata.id` (10,956 of
  slides' cells have one; nbformat's `id` too), else by source, a cell in place of one
  of the same kind being that cell changed; unchanged runs collapsed; a changed cell's
  two versions side by side, its lines marked, and in prose the words; outputs side by
  side when they changed, collapsed when not (execution counts ignored); a new
  notebook all added;
- the lab problems in Problèmes (`lab-format`, `lab-pairs`, …) link to the notebook's
  page in the language they name, and a changed notebook in Modifications to its
  before/after.

Neither nbconvert nor nbdime, against the plan: a notebook holds few things a page
shows, and nbdime's diff is a web app of its own, while the comparison needed the
same rendering as the page. studioz renders them itself: Markdown with markdown-it
(its math kept whole by an inline rule), code with Pygments (now a declared
dependency: slides re-locked in `310928d8`), outputs in nbconvert's order of types, ANSI colors and
carriage returns (tqdm's bars) included, consecutive stream writes merged; widgets
show their text (a progress bar's last state). MathJax 3.2.2's single
`tex-svg-full.js` (2.2 MB, vendored) typesets the math in the browser, as Colab does:
SVG, so no font to fetch. Outputs hold the notebook's own HTML, so the page showing it
is served sandboxed (`Content-Security-Policy: sandbox allow-scripts …`, an origin of
its own, so nothing in it reaches studioz's routes) and runs studioz's scripts only.
The view polls every 5 s and the TP list every 10 s: a notebook edited in the
person's own editor fires no `workspace-changed`; the listing is cached while the
notebook files are the same, the frame kept (scrolled where it was) while the notebook
is.

Tried on `studioz-dev` in Chrome (its deckz pointed at the worktree, put back after):
270 notebooks listed (`deckz labs list --json`: 1.8 s cold); the linear-regression demo
rendered as Colab shows it (pandas tables, seaborn plots, the cost function's math,
0.3 s for 650 kB); a 23 MB demo (two figures 8,600 and 13,000 px high) served in 0.8 s, its
images now loaded lazily since decoding them all at once froze the tab; edits to that notebook (a word, a
`return` line, an output, a new cell; put back after) in the before/after, a further
edit made outside studioz shown within 7 s; a `lab-format` problem clicked on a deck
page opened its notebook in English; "Ouvrir dans mon éditeur" opened GNOME Text
Editor, this machine's fallback for JSON (no notebook application installed).
**Found and fixed:** the frame took half the page (`.viewer-area`'s `--split` with no
editor beside it); the folders came in deckz's file order (`genai` after
`genai/fine-tuning`); outside edits never showed (no event: now polled); the
before/after's sticky header was half hidden. **Left:** the extension's screenshots
time out on the frame's URL opened on its own (its sandbox; inside studioz's page they
work); a markdown cell's changes show as source, not rendered; code lines aren't
marked word by word; the frame's height is its own (it scrolls inside the page);
notebook pages aren't in Ctrl+P (nor scenes').

**Increment 4: done** (2026-10-17). `deckz labs gpu pass NOTEBOOKS... [--short]
[--max-hours 4] [--write-outputs] [--dry-run [--json]] [--gpu] [--machine]`
(`deckz.labs.gpu_pass`):
- it rents the cheapest offer, queues and runs the notebooks, follows the queue
  every `--interval` (60 s), fetching, noting each finished run in `notes.md` and
  printing its report, runs the hooks, then destroys the machine, always: done, a
  run failed, the machine unreachable three polls in a row or stopped, past
  `--max-hours` counted from the rental (also each run's timeout), Ctrl-C, and
  SIGTERM (a handler raising `GpuPassStoppedError`, so the `finally` runs). Signals
  are blocked while it destroys the machine, so a second Ctrl-C can't leave it
  billing; a failed destruction names `deckz labs gpu down --machine …`;
- before renting anything, it refuses a machine already rented (the pass would
  destroy it), a missing notebook, `--write-outputs` with `--short` or on a hands-on
  notebook (`lab-outputs`), and whatever `queue` would refuse (`GpuRun.check`: no
  `SHORT_RUN` line, an unset variable, an unknown hook);
- `--write-outputs` (off by default: it overwrites) writes each run's outputs back
  once the machine is gone, for the runs that exited 0, as `deckz labs outputs` does;
- `--dry-run` rents nothing: the offer `up` would rent now (`GpuBackend.cheapest`),
  each notebook's last successful run time from the machines' `notes.md`, the main
  checkout's included from a worktree (a studioz workspace has none of its own),
  the estimate (`SETUP_MINUTES`, ten, added for renting and booting: a guess, not a
  measure) and the ceiling's cost; `--json` for studioz's modal (increment 5);
- `status --plain` gains each machine's GPU, price per hour and rental time
  (`GpuState.rented_at`, kept in `state.json` from now on), and the table its time
  and cost so far.

Progress goes to the log, the runs' reports to stdout; it exits 1 when a run failed
or didn't finish. Docs: the README's command list and the guide, which now leads with
`pass` (the steps one by one stay, for a machine kept between passes). Tests: the fake
runner, its machine "running" each notebook sent and rsync fetching a run of it: a
whole pass with outputs written back, a failed run left as it was, the ceiling (a fake
clock), Ctrl-C and a real SIGTERM, the refusals (nothing rented), the notes' last
successful run, the dry run's JSON, `status --plain`.

Tried on slides (from `studioz-dev`, its deckz pointed at the worktree, put back
after): the dry run of mlflow-registry-deployment's two demos found their runs in the
main checkout's notes (287 and 285 s) and today's cheapest offer, an RTX A4000 at
$0.134/h (no T4 on offer): 0.33 h, $0.04 estimated, $0.54 at the 4 h ceiling. The
refusals, on real notebooks; a missing notebook raised a traceback, now refused. No
machine rented. **Left:** a real pass, once the user says so (increment 5's trial);
the pass doesn't survive its own crash (`kill -9`): the machine stays rented, as
`status` shows (increment 5 finds it); the agent's refusal of `deckz labs gpu up|run|
pass` is increment 5's.

**Increment 5: done** (2026-10-18). In studioz (`studioz.gpu`):
- "Exécuter sur GPU…" on a notebook's page (both its languages) and as the TP view's
  title action (the notebooks ticked, kept across the list's reloads), and in the
  palette: a modal as VS Code's, from the workspace's `deckz labs gpu pass --dry-run
  --json`: the notebooks (each to untick, its last run time), full or short run,
  "enregistrer les sorties" (on by default for a full run of demos only, as deckz
  allows), the ceiling (twice the estimate rounded up to the half hour, at least 1 h,
  else deckz's 4 h), the GPU and its price, the estimate and the cost at the ceiling,
  that the machine is destroyed whatever happens; its button "Louer une RTX A4000 et
  exécuter (≈ 0,04 $)", the focus on Annuler, Enter in a field only estimating
  again; deckz's refusals said in it (a short run without `SHORT_RUN`, a pass
  already running);
- the pass a job of its own lane (`Job.lane`, kept with the job): a build doesn't
  wait an hour behind it, nor it behind a build; every option spelled out; stopped,
  it gets 300 s to destroy its machine before being killed (5 s otherwise), outside
  the request; its "Relancer…" reopens the modal on its notebooks;
- the status bar's item while a machine bills ("GPU RTX A4000 · 37 min · 0,08 $",
  orange like VS Code's remote indicator), from `deckz labs gpu status --plain
  --offline`, run again only when a machine's `state.json` changes, so a machine a
  crash left rented shows after a restart; a click opens the machines' dialog:
  "Arrêter la machine" stops the pass running it, asked first (its runs in progress
  are lost), else runs `deckz labs gpu down` at once; the job's own "Arrêter…" goes
  through the same question;
- the notification of a pass that wrote outputs carries "Voir l'avant/après" (the
  toast, the bell's center, and a click on the desktop one), as does the job in
  Tâches (`Job.link`);
- the agent's hook refuses `deckz labs gpu up|run|pass` but a dry run, saying the
  person starts it from "Exécuter sur GPU…".

In deckz: `status --offline` (what the checkout keeps, no call to Vast.ai), and
`GpuState.price` (the offer's, kept at the rental). Found by the real pass and fixed:
a run whose cells raised still exited 0 (the notebook carries on past them), so
`--write-outputs` wrote its broken outputs into the demo; such a run (an error output
in a cell not tagged `raises-exception`, or a failing `!` command) now fails the pass
and is never written back (no committed demo of slides holds an error output).

Tried on `studioz-dev` in Chrome (its deckz pointed at the worktree): the modal (2.8 s
to open, the dry run included), unticking a language, short mode refused for the
mlflow demo (no `SHORT_RUN`), Enter in the ceiling, the TP view's ticks kept across a
reload, a `state.json` written by hand for the status bar item and its dialog. Then,
the user agreeing, one real pass: mlflow-registry-deployment's French demo, full, a
1 h ceiling, estimated 15 min and $0.03 at $0.134/h. The $0.134 offer was taken
between the estimate and the rental, so deckz rented the next ($0.191/h, Estonia);
booting took 15 min (pulling Colab's image), the run 358 s; destroyed after 22.5 min,
about $0.07. The status bar item showed while it billed and went with the machine;
the job "terminée", its notification's "Voir l'avant/après" opened the notebook's
before/after. The run itself was broken (cell 13's `!landscape-classifier` exited 1
after 14 s, then four cells raised: the repository's demo or its DagsHub hook, not
studioz), which found the bug above; the notebook was put back. The hook's `uv run`
re-locked the workspace (it predates slides' `310928d8`) and reinstalled deckz, putting
`deckz.pth` back on `../deckz`; `uv.lock` was put back. **Left:** the estimate's price
is the offer's at that moment, and the setup allowance (10 min) was short by 5: the
modal could say the next offer may cost more, or deckz take a `--max-price`; the
mlflow demo's run fails at `!landscape-classifier` (slides' to look into: its notes
in `../slides--studioz-dev/.run/gpu/main/notes.md`); a GPU hook's `uv run` in a
workspace re-syncs its venv (a workspace's deckz pointed elsewhere for a trial goes
back to `../deckz`); a pass stopped while renting has no machine in the dialog (its
job's "Arrêter…" still stops it).

### Then, with the colleague

The acceptance test the operability plan already plans, extended: the colleague does a
week's real tasks through studioz, and every time they get stuck becomes a fix in
deckz, a skill, or studioz, in that order of preference.

### Phase 6: the agent's usage (planned 2026-10-21)

**What happened.** On 2026-10-21 the colleague spent their five-hour window in one
afternoon (13:57 to 16:42): 46 messages about 20 content files, nearly all from the
editor's "À propos de `file`, ligne N" prefill, mostly visual fixes ("c'est moche",
"aligne les T", a figure redone). Their session's transcript (Claude Code's
`~/.claude/projects/<workspace>/<session>.jsonl`, measured with a throwaway script)
gives:
- 257 model calls, all Opus 5.5 (`options()` sets no model, so the account's default);
  45.7 M tokens read from the cache, 0.33 M written to it, 166 k generated; Claude Code
  priced it at 15.10 $ at API rates.
- One conversation all afternoon: its context grew from 33 k tokens (the preset system
  prompt and tools, slides' 36 KB `CLAUDE.md`, the skills' listing) to 339 k, never
  compacted (the model's window is long). Each call reads it all again: a "merci"
  cost 153 k tokens at 14:37 and 271 k at 16:10; a "c'est moche" 1.4 M at 14:34 and
  2.3 M at 16:41.
- The cache lasts an hour (every write is `ephemeral_1h`; 14-minute pauses rewrote a
  few hundred tokens). No file was come back to after moving on.
- By purpose, share of the tokens read: exploring 37 % (78 calls: the file at hand and
  its neighbours, 40; how figures and assets are done, 29), rendering and looking 43 %
  (88 calls, most of them also editing or building: the agent builds with `deckz run
  file`, finds the page with `deckz show frames | grep`, converts it with
  `pdftocairo` and reads the PNGs in the same response), editing 9 %, building
  only 9 %, answering 18 % (45 calls with no tool). The 108 PNGs themselves weigh
  29 k tokens (3.2 M read again, 7 %).
- 49 of 122 writes were to `en/` files: the agent ported each change itself (the
  `stop` hook never had to block).

**What it means.** The cost is the long context, not any one task. Replayed with a
fresh conversation at each new file (same calls, starting again at 33 k tokens, which
the cache serves across conversations: the prefix is the same), the afternoon reads
12.3 M tokens instead of 46 M (÷3.7, an upper bound: a fresh conversation explores
the figure conventions again). On Sonnet it costs less again. Rendering is worth
keeping: the requests were visual, and the agent already batches build, conversion
and reading. Not worth doing: one session per file to come back to (it happened zero
times; a session resumed after the hour rewrites its whole context, about twelve
times a cache read; the file on disk and `git diff` carry what matters).

Each increment is usable on its own, in this order:

1. **The model**: done 2026-10-21. `options()` takes a model, `agent.DEFAULT_MODEL`
   (`sonnet`) unless `studioz --model` says otherwise; the agent panel's header names
   it, and each turn's end names the model that cost the most (Claude Code also calls
   Haiku on the side) as "Sonnet 5 · Usage estimé…". A workflow may declare `model`
   (its `then` follows it), checked by the schema; its turns put the running Claude
   Code on it (`set_model`), and the person's next message puts it back. `effort` is
   left to Claude Code. Tried for real: a message on `studioz-dev` ran on
   `claude-sonnet-5` (an id with no minor version, which `model_label` now reads), and
   in a scratch repository Sonnet, Haiku, then Sonnet again in one process. Found on
   the way: a turn's "Usage estimé" was Claude Code's `total_cost_usd`, which counts
   what its process spent since it started (three "OK" in a row reported 0.034, 0.044
   and 0.050 $), so each turn showed the sum of the turns before it until the process
   stopped (15 minutes idle); the colleague's figures were inflated so. A turn now
   shows the difference (`Conversation._turn_cost`). (A turn after a restart seemed to
   pay the cache's rewrite once, 0.10 $ against 0.01 $ the next: it didn't, see
   increment 2.) Left: the colleague's
   session ran 2 h 45 on one process at times, so measure the next one from Claude
   Code's transcript, not from the panel's sums.
2. **A new conversation for a new file**: done 2026-10-21. The editor's "Demander à
   l'agent" also gives the panel's form the file (a hidden `about`, cleared when the
   person empties the message or sends it). A conversation is about the file of its
   first such message (`.run/studioz/agent/about`); one about another file, while the
   conversation has entries, sets it aside first (`precedente/`: its session,
   transcript, pending question, file and cost, one conversation, the last) and
   starts afresh, the transcript opening on "Nouvelle conversation : autre fichier
   (`path`)", why in one line, and "Reprendre la précédente", which exchanges the two
   (only the last such button is live). A message without the editor (a follow-up),
   or from a dialog's ask, stays; a workflow's conversation is about several files
   (`MANY`) and never set aside. A deferred question is declined (the person wrote
   instead) and travels with its session; "Annuler ce tour" stays (the files are the
   workspace's, whichever conversation changed them). The pages follow a replaced
   transcript by `Conversation.epoch`. Tried in headless Chromium on `studioz-dev`
   with the real agent: two messages from the editor on `description.md` stayed one
   conversation, one on `schedule.md` started another (button live), "Reprendre la
   précédente" brought the first back, and asked "on which file was my first
   message?" it answered `description.md`, line 5. **Found and fixed:** Claude Code's
   `total_cost_usd` counts the *session's* spending, the earlier processes' turns
   included when it resumes it, so the first turn after a take-back or a restart
   showed the whole session's cost (0.20 $ for a turn whose transcript shows 45 k
   tokens read from the cache, nothing written: the 0.10 $ "rewrite" increment 1 saw
   was this). studioz now keeps the session's total (`spent`, set aside with it) and
   subtracts it; tried: 0.01 $ for a resumed turn. **Measured:** a new
   conversation's first turn read 22 k tokens from the cache (the system prompt and
   tools) and wrote 23 k (the first message's context: slides' `CLAUDE.md`, the
   skills, git's status), about 0.10 $ on Sonnet, against 0.01 $ for a follow-up at
   45 k. So starting afresh costs about 0.09 $ once, and saves each later call
   `context − 45 k` tokens read (0.3 $ per million): with the colleague's 5.6 calls
   per message, it pays back within a message from about 100 k, within three from
   about 65 k, and not at all on a short conversation. Increment 3 gates it on that.
3. **The context's size, shown**: done 2026-10-21. Each top-level
   `AssistantMessage.usage` (input plus cache read and write; a subagent's calls
   don't count) is kept as the conversation's size (`.run/studioz/agent/context`,
   set aside and taken back with it). The panel's header shows it ("Contexte :
   45 k", the exact count and why it matters in its title), and from `agent.LONG`
   (100 k) in red, with a line above the message box: "Conversation longue : l'agent
   la relit en entier à chaque appel…", its "nouvelle conversation" the header's
   button (still confirmed by a second click). Increment 2's automatic new
   conversation now waits for `agent.ASIDE_FROM` (60 k): below it, a message about
   another file stays, and the conversation is about that file from then on (the
   last file the editor named, not the first). The header had no room left: the
   model, the context and the account's usage now share a second line. Tried in
   headless Chromium on `studioz-dev` with the real agent: "Contexte : 45 k" after
   the first message (44,963 tokens), a message about another file stayed in the
   conversation (45 k < 60 k) and the conversation followed the file; with the size
   kept set to 183 k, the header turned red, the line showed, and its link asked
   "Oublier la conversation ?"; the header fits at 1,100 and 1,600 px. Left: no
   warning before a long task when a usage window is nearly full (open items).
4. **Less exploring, in slides**: done 2026-10-21. The colleague's transcript
   (`~/downloads/423cbff2-….jsonl`): about 25 calls (70 k characters of results)
   pieced together how the repository *writes* a figure: the conventions' "Graphiques",
   a plot module and its two `.yml`, `plots/utils.py`, `_lib.typ` read in four
   chunks (palette, nodes, edges, `sizes`), the theme's sizes, and two or three
   existing figures each time as models. Where figures go and how they're referenced
   was already in slides' `CLAUDE.md`. Two deckz frictions on the way, also hit in
   the trial below: `deckz run file content/nn/x.md` failed ("unresolvable file
   path": it wanted `nn/x`, while the editor's prefill and `git status` name
   `content/…`), and `deckz show frames` refused a `run file` preview's PDF ("isn't
   in the deck's PDF directory"), which the agent hid with `2>/dev/null` and replaced
   by `pdftotext` scripts to find a page. **Done:** in deckz, `run file`/`run section`
   take a path from the current directory or the repository's root too
   (`checking.content_relative`), and `show frames` reads a preview's PDF under
   `.run/` (`frames._built_by`). In slides (`b83c29fb`, merged by the user's
   go-ahead), `docs/figures.md`, in French for people too: the three kinds of
   figure, a Typst and a matplotlib skeleton (both built for real), credits,
   references and languages, Typst math (`bold(W)`, not `\vect`), the palette and
   node styles, the helpers' signatures, a model figure per kind, the three commands
   to see one page (tried as written), and replacing an image; one line in slides'
   `CLAUDE.md` ("Before drawing or redrawing a figure, read `docs/figures.md`"), and
   links from `conventions.md` and `HANDBOOK.md`. **Measured** with a headless
   Claude Code on Sonnet in a worktree (project settings, `auto` in the sandbox), on
   one request like the colleague's ("cette slide est trop verbeuse, fais une figure
   de la boucle d'entraînement par mini-batchs", `content/nn/gradient-descent.md`):
   without the guide, 15 calls, 718 k tokens read, 0.30 $, 210 s (three tries to
   build: the `content/` path, then `vect` in Typst math); with a first version
   naming no signatures, the same cost, the agent reading 200 lines of `_lib.typ`
   and placing the figure in `figures/typ/nn/gradient-descent/`; with the signatures
   and "the content file's folder, not the file", 10 calls, 465 k, 0.20 $, 101 s,
   no `_lib.typ` read, one model figure read, built right the first time. One run
   each: indicative.
5. **Measured again.** The colleague's next afternoon of the same kind, measured the
   same way: tokens per message, context at the end, model. Then decide on what is
   left: a `deckz` command giving a content file's rendered pages as PNGs (build,
   find the pages from the build's markers, convert) would save the page hunting, a
   few percent at most here; trimming slides' `CLAUDE.md` saves less, since the cache
   serves it.

### Phase 7: what the colleague's first afternoon found (noted 2026-10-21)

The user's notes from watching the colleague's first session (the one phase 6
measured), each with what the code does today. Each increment is usable on its own;
the first one first, since it stops a newcomer before anything else works.

1. **Logging in, and the first message**: done 2026-10-22. **Found:** through the
   SDK's client (studioz's, not `-p`), Claude Code 2.1.283 doesn't stop when it isn't
   logged in: it answers each message with an `AssistantMessage` whose `error` is
   `authentication_failed` and whose text is "Not logged in · Please run /login",
   then an `is_error` result, and stays up. The panel showed that English line twice
   (as the agent's text, then as "Le tour s'est arrêté sur une erreur"). A wrong model
   comes the same way (`model_not_found`, a value the SDK's `AssistantMessageError`
   doesn't list) with a diagnostic line on stderr. The SDK raises its "Check stderr
   output for details" (a constant) only when Claude Code exits non-zero without a
   result; with a result, it raises `ResultError` naming it. One such exit found: a
   session Claude Code doesn't have (another machine's, a cleared `~/.claude`), which
   fails at every message, its cause on stderr only ("No conversation found with
   session ID"). **Done:** an API error (`agent._API_ERRORS`: `authentication_failed`,
   `billing_error`, `model_not_found`, `server_error`, a generic one for the others; a
   limit stays a pause) is one entry, its fix in French first ("Claude Code n'est pas
   connecté à votre compte : dans un terminal, depuis le dépôt, lancez « uv run studioz
   login », puis renvoyez votre message"), Claude Code's words under it, and no second
   entry from the result. `options(stderr=…)` keeps Claude Code's last 20 lines per
   turn; a turn ending on an exception shows the last meaningful ones (diagnostics
   `[claude-code:tag] {json}` only when nothing else), "L'agent s'est arrêté :
   renvoyez votre message, il redémarre.", and for a lost session "« Nouvelle
   conversation », en haut du panneau, en commence une autre". Either failure calls
   `Agents.on_failure`, which `create_app` sets to `Login.forget`: the next status
   checks the login again, so the panel shows its login paragraph and refuses the
   next message instead of trusting a five-minute-old "logged in" (the commit
   message's proposal forgets it too on a failure). `studioz login` runs `claude auth
   login --claudeai`, then `agent.logged_in()`, and says the truth in French: the
   account, or why not and to run it again, exiting 1. **Tried for real** on
   `studioz-dev` (studioz from the worktree, headless Chromium): `--model
   claude-nonexistent-9` gave the model's entry; a bogus session id in
   `.run/studioz/agent/session`, the lost-session entry with Claude Code's line; with
   `CLAUDE_CONFIG_DIR` an empty directory, the panel's login paragraph (shown once the
   first `auth status` returned, between 3 and 10 s after a fresh start) and the
   message refused (409). The `authentication_failed` path itself, from the tests only
   (the fake client sends what the SDK repro showed): logging the person's own
   Claude Code out was not an option, and a copy of their credentials could rotate
   the refresh token under them. **Left:** what `claude auth login` exits with after
   a wrong code (interactive: `! CLAUDE_CONFIG_DIR=<empty dir> uv run studioz login`,
   a wrong code; studioz no longer depends on it); the terms never accepted, still
   not reproduced (it needs a fresh account's first login): its words now show under
   "L'agent s'est arrêté", so the next person to hit it can read them out, and then
   it gets its own entry and fix.
2. **Links open in a new tab**: done 2026-10-22. The PDF's links out of the deck
   (`deck.js`: `PDFLinkService` given `externalLinkTarget: LinkTarget.BLANK`; pdf.js
   adds `rel="noopener noreferrer nofollow"` itself; links within the deck still
   move the viewer), and every link of studioz's Markdown (`app._markdown`, a
   markdown-it `link_open` rule adding `target="_blank" rel="noopener noreferrer"`:
   the agent's text and the reports). The rest needed nothing: a notebook's frame
   already has `<base target="_blank">` and `allow-popups
   allow-popups-to-escape-sandbox`, the Problems' links open the editor, and
   studioz's own pages link out nowhere else. **Tried for real** in headless
   Chromium on `studioz-dev`'s Fortinet deck (external requests blocked): the title
   page's ORSYS link opened a tab, the page stayed and the editor stayed closed
   (`deck.js`'s page click already ignores links); a link in an agent entry (a
   transcript line written by hand, no agent turn) and one in the tool-calling
   agent notebook's Markdown each opened a tab. **Left:** a bare URL in the agent's
   text stays text (markdown-it's `linkify` needs `linkify-it-py`, a new dependency
   relocking slides; the colleague's afternoon had one link, written as a Markdown
   link).
3. **The agent knows the slide in view**: done 2026-10-23. Writing "cette diapositive
   est moche" is enough, without "Demander à l'agent". `deck.js` (`showSlide`) keeps
   the frame of the page in view (`viewer.currentPageNumber` in `/cadres`'s frames)
   in `body`'s `data-slide`, as JSON, at each page change, each build's new frames
   and each view change; none on a page with no frame (title, outline, a part's
   title) nor in the before/after view, where the PDF isn't shown. The agent panel
   shows it above the message box ("Diapositive en vue : p. 10 · Emploi du temps",
   its file and line in the tooltip) and posts it with the message (`slide`, beside
   `about`); other pages post none. `agent.Slide.parse` reads it (anything else is
   no slide), and `Conversation.send(slide=…)` tells the agent a line before the
   message ("(La personne regarde, dans studioz, le cadre « Emploi du temps » :
   decks/…/schedule.md, ligne 1, page 10 du PDF.)"; for a frame whose source the
   build didn't find, its page and title), the transcript keeps the person's words
   with the slide in small under them (the entry's `detail`). **Decided** (with phase
   6's increment 2): the slide's file is the message's `about` when the last message
   written on a deck's page had another file's slide (`slide` in the agent's
   directory, in `_KEPT`, so a conversation taken back keeps its own); compared by
   file, not by slide, since `about` is a file: another slide of the same file, or
   "merci" on the same one, stays a follow-up, and the editor's `about` wins. **Tried
   for real** in headless Chromium on `studioz-dev`'s Fortinet deck: page 1 posted no
   slide and hid the line; page 10 showed and posted `{"page": 10, "title": "Emploi
   du temps", "file": "decks/orsys/INTRA/2026-10-fortinet/content/about/schedule.md",
   "line": 1}`; the before/after view hid it, coming back showed it again. One real
   turn (Sonnet, 0.11 $, 8 s): "Cette diapositive est-elle trop chargée ?" made the
   agent read `schedule.md` at once and answer about its two bullets. Found on the
   way: a first version compared the slide with the previous one field by field, and
   on a frameless first page never set `data-slide` at all (`null` equal to
   `undefined`); it now compares the JSON. **Left:** the person can't drop the slide
   from a message (VS Code's chat lets one untick the current file); a title shows
   Typst's markup as the build recorded it (`*Skills*\ :`), which the agent reads
   well but the line shows raw.
4. **The PDF's bookmarks**: done 2026-10-23. **Found:** Typst's outline has the
   deck's parts, sections and subsections, not its frames (`mutool show … outline`
   on the Fortinet handout: 20 entries on 3 levels, "Informations sur la formation"
   to "Quiz"). **Placed** as VS Code's Outline below its Explorer: a "Plan" section
   at the bottom of the Formations view, on a deck's page only (`_sidebar.html`;
   the view becomes a column, the deck list and the Plan, at most 55 % of it, each
   scrolling on its own), foldable from its title (kept per browser). `deck.js`
   (`loadOutline`) builds the tree from `pdf.getOutline()` after each PDF load, each
   heading's page from its destination (`getDestination`, `getPageIndex`); parts
   open by default, and what the person opens or closes stays across builds (keyed
   by the titles from the top). A click goes to the heading
   (`linkService.goToDestination`), back to the slides from the before/after view;
   the heading of the page in view is marked (`markOutline`, at each page change),
   or the outermost closed heading around it, scrolled into view in the tree. A PDF
   with no outline says so. **Tried for real** in headless Chromium on
   `studioz-dev`'s Fortinet deck: 20 headings, the five parts open; pages 1 and 2
   (before the first heading) marked none; "Garde-fous" went to p. 19 and was
   marked; at p. 41, "Évaluer un prompt" (closed) stood for its "Démonstration",
   which was marked once opened; "AI Act" clicked from the before/after view went
   back to the slides at p. 77; the Plan folded stayed so after a reload. No page
   error. Not tried for real: a heading opened kept across a rebuild (the code keys
   it like the deck tree's folders). **Left:** the frames themselves aren't in the
   tree (the build's `/cadres` has them, with their files: a third level of frames
   under each section would make the Plan a table of contents of the slides).

**Also left** (from the review of what's open, 2026-10-21; not the colleague's
notes), most useful first:
- `studioz/tests/test_agent.py::test_the_agent_asks_and_waits_for_the_answer` failed
  once under `-n auto` (2026-10-22), then passed six runs: another timing test.
- deckz's Ctrl-C timing tests (`test_interrupt_does_not_wait_for_running_compilations`,
  `test_ctrl_c_stops_the_build_at_once`) fail in the pre-commit hook about one run in
  three: make them wait on the event, not a fixed sleep.
- A warning before a workflow (a QA, the translation backlog) when the five-hour
  window is nearly full; a limit pause that survives a studioz restart; an ordinary
  failing command (`grep` finding nothing) shown as "Refusé ou en échec".
- `deckz status` takes about 10 s on slides, 6 of them the lab checks each reading
  every notebook again: read them once.
- Ctrl+P finds decks, not content files nor scenes; nor recent ones first.
- Small: a toast covers the agent's send button; the Tâches log isn't kept at its
  end; the watches and agents aren't counted in the memory item nor held under the
  threshold; a GPU pass's estimate may change before the machine starts (say so, or
  a `--max-price`).

### Phase 8: what you publish no longer depends on where you click (planned 2026-10-23)

**What happened** (2026-10-23, on the colleague's machine). They had opened a
workspace a few days earlier, then pulled in their main checkout and never updated
the workspace. Its branch still started from the 10-16 `main`. From it, studioz's
Publier ("Les carnets du dernier commit de l'espace…", `actions.PUBLISHABLE`) ran
`deckz labs publish`, which publishes HEAD's notebooks (`labs.publishing.
_published_notebooks`, `ls-tree HEAD`). Its parentless commit (`labs` 02b99530,
`labs-codespace` 23173cba, 11:26) replaced the user's publish of 10-22 23:33
(`labs` 811c7833): all 64 notebooks it changed went back to an older version from
slides' history (e.g. `advanced-hands-on-fr` from `173364e4`, 10-22, back to
`2ff593cf`, 10-16), and 4 files of `labs/published` to their 10-15/16 versions,
which dropped the Codespace's short `lab` command (`0391c70a`) that the PDFs cite.
Nothing it published was newer than slides' `main`. The user's checkout's `deckz
status` then said "64 committed notebooks not as published", but only once fetched:
studioz runs `deckz status --json --no-decks` without `--fetch`
(`problems.status_command`), so it compares with the remotes as last fetched. The
colleague had also rendered videos in the main checkout and then tried to publish
them from the workspace, where they weren't: renders are gitignored, and a
workspace gets the main checkout's only once, when `deckz worktree add` seeds it
(`worktree.seed`). Their exact error wasn't seen.

Nothing in deckz stopped any of it: `labs publish` neither fetches the upstream
branch nor refuses a HEAD behind it, nor notices a notebook going back to an older
version of itself. The common cause is that what gets published depends on the
checkout the button or the command runs in. Most useful first; increments 1 to 3
and 5 are deckz's (`deckz labs publish`, `deckz videos publish`, `deckz worktree`
are what people run without studioz too), increment 4 is studioz's and the
handbooks'. Increments 1 and 2 change what deckz does for every slides session:
tell them before merging (`ListAgents`, `SendMessage`). Same procedure as "Starting
phase 7".

1. **Publish what's on the upstream branch**: done 2026-10-23 (deckz side and the
   publish dialog; the user tries the publish itself, see Left). **Decided**
   (2026-10-23): publish from the upstream commit, not HEAD. `deckz.upstream`
   holds the branch every checkout meets on (`upstream()`, the main checkout's
   branch's upstream, the same `studioz.sync.upstream` finds; `source()`, fetched
   or as last fetched, HEAD without an upstream; `unpushed()`, `missing()`,
   `known_blobs()`). `deckz labs publish` fetches it and publishes its notebooks and
   `labs/published` files (`labs.publishing.publish(source=…)`), refusing HEAD's
   commits changing either that it lacks ("these commits change the labs and aren't
   on origin/main yet: … Push them first"). The content checks run on the working
   tree when HEAD's two directories are the upstream's, else on an export of the
   upstream commit (`checking.export_tree`, under `.check/upstream`: 0.8 s on
   slides, then 15 s of checks, as on the working tree). **Changed from the plan:**
   the second net refuses to replace a published version the source's history
   doesn't hold (`git rev-list --objects <source> -- labs/notebooks labs/published`,
   0.09 s on slides), unless `--replace-unknown`, rather than "an older version":
   with the upstream as the source, its current version is never older but by a
   deliberate revert, and what can still go wrong is someone (an older deckz, the
   colleague's) having published commits the upstream never got; the 2026-10-23
   publish passes it (each of its blobs is in slides' history), so the user's
   republish goes through. `deckz status`'s Labs section compares the same commit
   ("64 notebooks of origin/main not as published", its summary "origin/main
   compared with labs/main as fetched on …") and lists the unpushed lab commits;
   tried on a scratch copy of slides (local bare stand-ins for origin, labs and
   labs-codespace holding today's state, a worktree on the colleague's 10-16
   `2ff593cf`): the stale worktree and the current checkout now report the same
   64 notebooks and 4 files, where the stale one compared its own HEAD before,
   matching the bad publish, so it showed nothing to publish. Videos: rather than
   stamps computed from blobs, `deckz videos publish` refuses while the scenes'
   sources (each scene's `sources()`, and any `.py` under `scenes_dir` the upstream
   has otherwise) differ from the upstream's (`videos.publishing.differing_sources`,
   the working tree's bytes against the upstream's blobs: 0.2 s on slides), naming
   them and the fix (push the commits changing them, update to the upstream,
   commit): a render fresh here is then fresh for the upstream. On the scratch copy,
   the 10-16 worktree differs by one (`figures/scenes/nn/weight_initialization.py`),
   the current checkout by none. studioz's publish dialog says it publishes from
   origin/main whatever the workspace (`actions.PUBLISHABLE`), and when the
   workspace has unpushed commits or lacks some of the upstream's, says what deckz
   will refuse and offers "Synchroniser d'abord…" (the Sync dialog); found on the
   way: it wrote "1 commit de cet espace ne est pas encore", now "n'est". Tests: the
   stale worktree publishing the upstream's notebook, the unpushed commits refused,
   the checks run on the export, the unknown version refused then replaced, the
   videos' sources compared and the command's refusal, the dialog. **Left:** the
   user tries `deckz labs publish` for real (the repository's Bash hook refuses an
   agent any `labs publish`, even against the scratch copy's local remotes: from
   `../deckz-studioz`, `bash <scratchpad>/trial-setup.sh` then `uv run deckz labs
   publish --skip-checks --workdir <trial>/slides--stale` publishes the upstream's
   notebooks into the stand-in); a chained "Synchroniser puis publier" (one dialog
   doing the Sync's check and push then the publish) if "Synchroniser d'abord" turns
   out to be a step too many.
2. **Workspaces stay current**: done 2026-10-23. `studioz.updates`: a `Fetcher`
   fetches the upstream branch's remote from the main checkout with
   `--no-write-fetch-head` (the remote-tracking refs are shared by every worktree,
   and nothing else changes there; `sync.state` takes its time, so "récupéré il y a"
   stays true), at startup and every 15 minutes (a lifespan task,
   `create_app(fetch_every=…)`, None in tests) and when the home page or a workspace's
   page opens, at most once a minute (in a thread: the page doesn't wait). After each
   fetch, every workspace behind it with no commit of its own, nothing uncommitted
   (untracked files included), no rebase, and no job nor agent turn running
   (`Conversation.busy`, new) is fast-forwarded (`git merge --ff-only`). After any
   update, studioz's or the person's from the Sync dialog (Mettre à jour, Mettre à
   jour et vérifier, and Continuer ending a rebase, counted from `ORIG_HEAD`), the
   workspace's `deckz setup` runs in a thread, as `workspaces.create` runs it
   (`--force` when `package.json` changed; slides' `uv sync` step runs every time),
   and `.run/studioz/update.json` keeps what the update brought (the upstream's
   commits the old HEAD lacked, not the rewritten own ones) and what the setup
   reported missing or failed. The top bar's banner beside the workspace's name
   (`_currency.html`, every 30 s and on `workspace-changed`) says "Mis à jour
   automatiquement il y a 3 min, 1 commit de origin/main · deckz setup : 3 problèmes
   (…)", the details in its tooltip, until closed (12 hours, or for as long as the
   setup reports a problem); otherwise, for a workspace behind, "origin/main a 1
   commit que l'espace n'a pas" and "Mettre à jour…" (the Sync dialog); a failed
   fetch says so. The build and upload dialogs load the same route's notice ("…
   ce que vous construisez ou envoyez n'en tient pas compte", "Mettre à jour
   d'abord…"; the publish dialog has its own since increment 1); the home page's
   count of commits behind links to the workspace. **Tried for real** on the scratch
   copy of slides (studioz from the worktree, port 8431, headless Chromium), with a
   workspace `clean` and one `mine` holding a commit of its own, a commit pushed to
   the stand-in origin before studioz started: at startup `clean` was
   fast-forwarded and set up (its `uv sync` failing, the scratch copy having no
   `../deckz` beside it: the banner listed it), `mine` untouched, its banner and the
   build dialog's notice offering the update, which (from the Sync dialog's "Mettre
   à jour seulement") rebased its commit and ran its setup, recorded as the
   person's. Found on the way: the notice's `<div>` inherited the build form's
   `hx-target` and replaced the whole dialog (now `hx-target="this"`); the banner's
   first version ran past its 45vw and hid its ✕ (the text now truncates, the button
   stays). Tests: the fetch moving the branch, writing no `FETCH_HEAD`, failing; a
   clean workspace fast-forwarded and set up, `--force` for `package.json`; one with
   its own work offered the update, its banner and notice; a busy one waiting; the
   person's update set up too. **Left:** nothing tells a busy workspace's person
   that its fast-forward waits for the job or the turn (the next fetch does it); the
   setup's details show in a tooltip only.
3. **A render made in one checkout is found from the others**: done 2026-10-23.
   `deckz.stamps.is_fresh`, which every builder asks before building (deckz's Typst
   figures, slides' plots and SVG copies, the videos' `state`), now calls
   `stamps.adopt` for an output missing or stale here: the first checkout of the
   repository (the main one, then the worktrees, in git's order) whose copy is
   stamped with this checkout's digest is copied (`copy_file_if_changed`, atomic),
   with its `companions` (a video's poster and `.quality`, which must exist there),
   the stamp written last, and not at all if the stamp there changed during the copy
   (a rebuild meanwhile). **Changed from the plan:** in `is_fresh` rather than at
   each entry point (`deckz run`, `videos render`, `setup`, publishing), since the
   stamp is only known where the builder computes it; so `deckz videos list` (and
   studioz's Vidéos view) copies too, which shows a render made elsewhere as fresh
   rather than missing. `deckz setup`'s videos item (run after studioz's Update)
   and `deckz videos fetch` count a render missing only once the copy failed;
   `deckz status`'s Videos section still checks `is_file()` only (a status stays
   read-only; its fix, `deckz videos render`, then copies). The checkouts are read
   from git's own files (`.git`, `commondir`, `worktrees/*/gitdir`), not
   `deckz.worktrees.worktrees` (which lists `ws/` branches only and runs git), and
   not cached (a `--watch` sees a worktree added later). **Measured** on slides
   (main + 4 worktrees): 0.7 ms per output not fresh here, about 0.4 s for a
   fresh clone's ~600 outputs; nothing for a fresh output. **Tried for real**: a
   worktree of slides' `main` (`deckz worktree add adopt-trial`, its deckz pointed
   at `../deckz-studioz`, removed after), with a plot, its SVG copy, a Typst figure
   and a video (poster, quality, stamp) deleted: `deckz run assets` copied the
   three figures from the main checkout (5.5 s, as fast as with nothing to do;
   each logs "copied from …, where it's up to date"), `deckz videos list` the
   video, all byte-identical to the main checkout's; `--json`'s stdout stays clean
   (the log goes to stderr). Tests: copied from a worktree and into the main
   checkout, the main checkout preferred, a candidate lacking a companion skipped,
   a copy rebuilt meanwhile left unstamped, outside a repository, the videos'
   `state` and `fetch_renders`. **Left:** among several fresh copies the first
   wins, even a draft when another checkout has the published quality; the copy
   isn't a hard link (135 MB of videos on slides: a second copy per checkout, as
   seeding already makes).
4. **One place to work, for studioz's users**: done 2026-10-23. The home page's
   "Source des espaces" panel (`_source.html`, `GET /source`, every 60 s, every 2 s
   while its setup runs) shows the main checkout's path and branch, how far behind
   the upstream branch it is (as last fetched), its commits the upstream lacks and
   its uncommitted tracked files, with "Actualiser" (`POST /source/actualiser`,
   `updates.refresh_source`): refused while a tracked file has uncommitted changes
   (naming up to 5; untracked files are left to git, which refuses the
   fast-forward only if it would overwrite one), then the shared `Fetcher` fetches,
   refused while the main checkout has commits of its own (it can't move without
   rewriting them: push them, or `git pull --rebase` in a terminal), else `git
   merge --ff-only` of the upstream's tracking ref (rather than `git pull`: no
   `FETCH_HEAD`, as increment 2) and `updates.after_update` in a thread, recorded in
   the main checkout's `.run/studioz/update.json` (gitignored) and shown under the
   panel with `deckz setup`'s problems listed, until closed (`POST /source/vu`).
   slides' `HANDBOOK.md` ("Installer") says that with studioz one works only in
   workspaces, the main checkout moving by Actualiser alone, and that a figure or a
   video built in one checkout serves the others (increment 3); increment 5 added
   what happens to a worktree's renders when it goes. studioz's README says the
   same. **Tried for real** on a scratch copy of slides (a bare stand-in origin, a
   main checkout cloned from it, one commit pushed from another clone; studioz from
   the worktree, port 8431, headless Chromium): the panel said "en retard de 1
   commit sur origin/main"; with `HANDBOOK.md` edited, Actualiser refused, naming
   it, HEAD unmoved; edited back, Actualiser fast-forwarded it in 2.4 s, the setup
   ran (its `uv sync` failing, the scratch copy's `../deckz` being a symlink: the
   panel listed the 3 problems). Found on the way: the problems' `<ul>` inside the
   note's `<p>` split the box (a `<p>` can't hold a list); now a `<div>`. Tests:
   the panel, the refresh and its setup, the note closed, refused for uncommitted
   changes and for commits of its own, no upstream. **Left:** nothing stops a
   `deckz run --watch` someone left running in the main checkout from seeing its
   files move; the setup's VIRTUAL_ENV warning (studioz's environment leaks into
   `uv` there: harmless, uv ignores it).
5. **A worktree's renders outlive it**: done 2026-10-23. `deckz.worktrees.hand_over`
   lists the worktree's stamped outputs among its ignored files under
   `worktree.seed` (`git ls-files --others --ignored`), each with its companions
   (the unstamped files beside it named after it: a video's poster and `.quality`,
   a plot's credits). `deckz worktree land`, once the main checkout is
   fast-forwarded, copies there each one it lacks (companions first, the stamp
   last); `deckz worktree remove` does the same, then sets aside each one the main
   checkout holds stamped otherwise, unless another checkout or the store already
   holds it with the worktree's stamp, in `<git common dir>/deckz/renders/<stamp>/`
   (the output at its path, its stamp, its companions: `stamps.set_aside`), which
   `stamps.adopt` searches after the checkouts ("copied from the builds set
   aside"). `remove` returns `Removed(kept_branch, renders)` and prints what it
   copied and set aside; `land` returns the copies too. `deckz setup`'s new item
   "builds set aside" (`setting_up.set_aside_builds`, last, after the videos
   adopted theirs) drops an entry a checkout holds again with its stamp, or older
   than `stamps.STORE_DAYS` (30; the entry's time is reset when set aside).
   **Changed from the plan:** neither command overwrites the main checkout's copy,
   nor tells "fresh" from "stale" there: only a builder knows the digest of its
   sources now (deckz's Typst figures, slides' plot builders, the videos), and
   `worktree` can't run them for the main checkout. So `land` copies only what the
   main checkout lacks; one it holds stamped otherwise, after a land, is adopted
   from the worktree by its next build (increment 3), or from the store once the
   worktree is removed. And `remove` sets aside every output the main checkout
   holds stamped otherwise, including those built for sources that never reached
   the upstream branch (rather than naming them as lost): a copy adopted only for
   an exact stamp is never wrong, a branch kept by `--force` gets its renders back
   if it's checked out again within 30 days, and the cost is disk for 30 days at
   most. studioz's Fermer now asks in the workspace's row (`GET
   /espaces/{name}/fermer`, `_close_confirm.html`, from `worktrees.pending_renders`,
   a dry run) rather than the browser's `hx-confirm`: "2 rendus (figures, vidéos)
   que le dossier principal n'a pas y seront recopiés. 2 rendus faits pour d'autres
   sources que celles du dossier principal seront mis de côté pour 30 jours : il
   les reprend une fois ses sources à jour (Actualiser)." (the paths in a tooltip);
   the refusal row says the same, the closed row what was done. **Tried for real**
   on a scratch clone of slides (`git clone --shared`, the main checkout's 329 MB
   of builds copied in, deckz-studioz's code on `PYTHONPATH` over slides'
   environment): a worktree editing one Typst figure, adding one and editing a
   scene (rendered at `-q l`), its commits on a branch standing in for origin:
   `remove` copied the new figure's 2 SVGs and set aside the edited figure's 2 and
   the video (poster and quality with it); the main checkout, fast-forwarded to
   that branch, then compiled nothing (`deckz run assets`: both SVGs "copied from
   the builds set aside", stamped as the worktree's) and `deckz videos list`
   showed the trial's render (draft); `set_aside_builds` dropped the 3 entries. A
   second worktree: `land` copied the new figure (0.6 s), `remove` set aside the
   edited one (0.75 s; 9 s before the companions were indexed by directory), which
   the main checkout's next build adopted. `pending_renders` takes 0.3 s on a
   worktree's ~2100 ignored files. studioz from the worktree on the scratch clone
   (port 8431, headless Chromium): Fermer showed the counts above, its Fermer
   closed and said "y ont été recopiés", "ont été mis de côté". Tests: land copies
   what the main checkout lacks and overwrites nothing; remove copies and sets
   aside, the main checkout adopting the set-aside copy with its poster once its
   stamp matches, then `prune` dropping it; the dry run changing nothing; nothing
   set aside that another checkout holds; `prune` by age; `deckz setup`'s item;
   the Fermer row, the refusal and the closed row. **Left:** a build adopted from
   the store logs a line per output, not a summary; `agent_checkouts`'s removal
   (Claude Code's `WorktreeRemove` hook) hands over too but reports nothing.

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

  **Done** (2026-10-18, `studioz.memory`): the status bar shows the memory available
  (`MemAvailable`, Linux only; nothing elsewhere), orange under the threshold,
  `studioz --min-free-memory` (3 GiB by default, announced at start; 0 never holds).
  A job needing memory (a build, a render) about to start under it waits, "en attente
  de mémoire" with what's available and "Lancer quand même"; studioz checks again
  every 5 s and starts one held job per check, since a build's memory grows over its
  first seconds. Uploads, publications, GPU passes and `down` never wait (a `down`
  held back would leave a machine billing). Tried on `studioz-dev` with the threshold
  at 64 GiB: every deck's build and the Fortinet deck's held (the jobs item "1 en
  attente de mémoire", the memory item orange), the first stopped while held, the
  second started by "Lancer quand même" and built; at 3 GiB, the item plain (6.4 GiB
  available of 15.3). **Left:** the watches, the baselines' builds and the agents
  aren't jobs and never wait; what takes the memory isn't shown (each workspace's
  watch and agent).
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
