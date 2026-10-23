# studioz

Notes for working on studioz, loaded when Claude works under `studioz/`. What
studioz is, and its rule that anything it needs goes into deckz, are in the root
`CLAUDE.md` (its "studioz" section).

`studioz.app` holds the FastAPI routes (server-rendered Jinja pages in French,
`templates/`, with htmx), `studioz.workspaces` what the pages show of `deckz
worktree`'s worktrees (studioz's own state goes in each workspace's
`.run/studioz/`), and `studioz.local_only` refuses requests not naming a local host,
and changes not coming from studioz's own pages (DNS rebinding, cross-site
requests): every route that changes something is a POST.
A workspace's pages share VS Code's layout (`workspace_base.html`, `static/layout.js`):
an activity bar choosing the sidebar's one view (Formations, a tree of the decks
without the folders they all share; Vidéos; TP; Modifications; Publication; Avec
l'agent), the
page above a panel of tabs (Problèmes; a deck's Construction, opening by itself
when a build fails; Tâches, where a job started from a dialog goes on, the dialog
closing on the response's `job-started` event), the agent on the right, all resizable
and hidden by Ctrl+B / Ctrl+J / Ctrl+Alt+B (kept per browser), and a status bar. On
a deck page the PDF and the editor share the page by a ratio (`--split`), side by
side or, when narrow, one above the other. Ctrl+P (or the title bar's search) finds a
deck, Ctrl+Maj+P, F1 or ">" a command (`static/palette.js`): the commands are hidden
buttons (`_commands.html`) carrying what the page's own buttons carry, so running one
clicks it.
Mind class names: pdf.js's stylesheet and pages use `.page`, `.sidebar`, and the deck
page has `.deck`, `.waiting` (`[hidden]` wins over any of them).
`studioz.watches` runs one `deckz run --watch` per workspace (the workspace's
own deckz, every option spelled out) for the deck page in front of the person,
and reads its state from the log (`deckz.pipelines.watch`'s messages: keep them
in step); the page follows it through server-sent events and shows the
handout in pdf.js, and the watch stops once no page has followed it for 30 s.
A link out of studioz (the PDF's, the agent's Markdown, a notebook's) opens a new
tab.
A click on a page opens its frame's source (`deckz.analyzing.frames`, from
what the build recorded, never compiling in studioz's process) in the editor
beside it (`static/editor.js`, CodeMirror), which saves through
`studioz.sources`: only content and deck files, and never over a version of
the file the editor didn't read.
`studioz.problems` fills the panel's Problèmes tab: the workspace's own
`deckz status --json --no-decks`, run again in the background whenever the
workspace's files changed (`git status`), plus the deck on screen's build
failure and the frames its build recorded as shrunk; each problem naming a
file links to the editor.
`studioz.changes` fills the Changes panel (`studioz.background` runs a
workspace's slow commands, `deckz status` and `deckz show affected`, again
when its files change), `studioz.baselines` keeps each deck's handout as of
the last commit (from the live build of a clean workspace, else built in a
scratch checkout next to it), and `studioz.comparison` matches frames by
title and compares their rendered pages for the "Avant/après" view.
`studioz.commits` backs the Commit dialog: the chosen files as they are on
disk (the index is reset, then exactly those are staged), git's hooks run
by the workspace's own deckz (its `.venv/bin` first on the `PATH`), and the
`Lang-sync` rule asked beforehand from deckz's `i18n_stale.one_sided` with
the pairs `changes.LangPairs` keeps per workspace (about a second to find). Its draft
(message, files chosen, `Lang-sync` answer) is kept in `.run/studioz/commit-draft.json`
as the person writes it, and an opening dialog starts from it.
`studioz.sync` backs the Synchronisation dialog: fetch and rebase onto the
main checkout's upstream branch (a conflict fixed in the editor, then
continued, or aborted), the commits checked as they'd be pushed (`deckz
check --staged` with a temporary `GIT_INDEX_FILE` holding the commit, and
`deckz hooks check-commits`), then a push of exactly the commit checked,
never forced. The dialogs open through `static/dialogs.js`, so that a panel
reloading under its button doesn't drop the answer.
`studioz.jobs` runs the long commands a person starts (`studioz.actions`: a
deck's or every deck's full build, `deckz upload` after showing `deckz upload
--dry-run`, `deckz labs|videos publish`), each workspace's one after the other,
their logs in the panel's Tâches tab; deckz's own refusals still decide. Jobs are
kept in the workspace's `.run/studioz/jobs/`, so they outlive studioz (those it
stopped or a crash left running are "interrompues"); a build runs again as is, an
upload or a publication reopens its dialog. A build or a render waits while the
machine has less memory available than `studioz --min-free-memory` (3 GiB;
`studioz.memory`, `/proc/meminfo`, shown in the status bar), one held job started per
check, unless "Lancer quand même"; uploads, publications and GPU passes never wait (a
`down` held back would leave a machine billing). `static/notifications.js` notifies each
job's end as VS Code does (a toast, the status bar's bell, a desktop notification
when the page is hidden), from the status bar's jobs item.
`studioz.videos` backs the Vidéos view and a scene's page (`static/video.js`):
the workspace's `deckz videos list --json`, its render in a `<video>` beside its
module in the editor (`studioz.sources` edits `.py` under the scenes' directory
only), "Brouillon" and "Rendu final" as jobs, and the before/after: renders
aren't committed, so the last commit's are hard links studioz keeps under
`.run/studioz/videos/`, which survive the next render because deckz moves a
render into place rather than writing into it (keep it so). `deckz status`
runs again when a render's stamp or quality changes (`problems.renders`).
`studioz.labs` backs the TP view and a lab notebook's page (`static/lab.js`): the
workspace's `deckz labs list --json` (cached while the notebook files are the same,
since the pages poll: a notebook edited in the person's own editor fires no event),
the notebook rendered as Colab shows it, or its changes since the last commit cell by
cell, by `studioz.notebooks` (markdown-it, Pygments, MathJax in the browser; no
nbconvert nor nbdime). The page holding the notebook is served sandboxed, its scripts
studioz's own (`notebooks.frame_headers`): outputs carry the notebook's HTML, and
nothing in it may reach studioz's routes. A notebook isn't edited in studioz (it's
JSON): "Ouvrir dans mon éditeur" opens it with the system's application.
`studioz.gpu` runs GPU passes: "Exécuter sur GPU…" (a notebook's page, or the
notebooks ticked in the TP view) opens a modal from the workspace's `deckz labs gpu
pass --dry-run --json` (the GPU, its price, the estimate, the ceiling), its button
naming the cost and the focus on Annuler (Enter in a field only estimates again);
the pass is a job of its own lane (`Job.lane`: it doesn't hold the builds back),
every option spelled out, given 300 s to destroy its machine when stopped before
being killed. The status bar shows each machine billing from `deckz labs gpu status
--plain --offline` (run again only when a machine's `state.json` changes), so a
machine a crash left rented shows too; "Arrêter la machine" stops the pass running
it, asked first, else runs `deckz labs gpu down`. A pass that wrote outputs links
its notification to the notebook's before/after (`Job.link`).
`studioz.agent` backs the agent panel beside every workspace and deck page:
one Claude Code conversation per workspace through the Agent SDK, logged in as
the person (never an API key: studioz removes `ANTHROPIC_API_KEY`), on `studioz
--model` (`sonnet`) unless a workflow declares its own model for its turns
(`set_model` on the running process), in the
workspace with the repository's project settings, `auto` permissions in the
sandbox, and a `PreToolUse` hook refusing the `git` commands that commit, push
or move a branch (the person commits from studioz), and `deckz labs gpu up|run|pass`
but a dry run (a pass starts from its modal, which gives the cost). An API error
Claude Code answers with (`AssistantMessage.error`: not logged in, a wrong model) is
one entry naming its fix (`agent._API_ERRORS`), and Claude Code exiting shows its
stderr's last lines (`options(stderr=…)`); either makes `Login` check again at once
(`Agents.on_failure`). A question it asks
(`AskUserQuestion`) is a form in the panel: a `PreToolUse` hook defers it, so
the turn ends on it and it waits in `.run/studioz/agent/question.json`, across
restarts, until the answers resume the session, where Claude Code runs the call
again through `can_use_tool` (a question alongside other tool calls can't be
deferred: the turn then waits in `can_use_tool`). `studioz.checkpoints` snapshots the workspace's files around
each turn (a private index, trees under `refs/studioz/`), so that "Annuler ce
tour" puts back what the last one changed. The panel shows the account's usage
windows and each turn's usage (its model, and its cost: Claude Code reports what
its session spent so far, `Conversation._turn_cost`); a turn stopped by a usage limit pauses the
conversation, which resumes by itself at the reset time. `studioz.asks` holds
what the dialogs ask it ("Traduire avec l'agent", "Demander à l'agent de
corriger", of resolving a conflict: prompts studioz writes from the dialog) and
the Commit dialog's proposed message (one exchange, no tool). Its session and transcript
are kept in `.run/studioz/agent/`, resumed after a restart; the page follows it
through server-sent events, which end when studioz stops (`Studio.closing`). Each
message reads the whole conversation again: the panel shows the context's size (the
last call's, kept in `context`) and suggests a new conversation past `agent.LONG`. A
conversation is about one file: the editor's "Demander à l'agent" names it (`about`),
and from `agent.ASIDE_FROM` a message about another file sets the conversation aside
(`precedente/`, one, which "Reprendre la précédente" exchanges back) for a new one;
a follow-up typed in the panel stays, and a workflow's conversation (`MANY`) is never
set aside. On a deck's page, `deck.js` puts the slide in view (its frame from
`/cadres`; none on a frameless page nor in the before/after view) in `body`'s
`data-slide`, the panel shows it above the message box and posts it: the agent is
told it in a line before the message (`agent.Slide`), the transcript shows it under
the person's words, and its file is the message's `about` when the last message
written on a deck's page had another file's slide (`slide`, kept with the
conversation), so that "merci" stays a follow-up. A session's total so far, which
a turn's cost subtracts, is kept in `spent`, since a resumed session counts from it.
`studioz.workflows` reads the workflows a workspace's own `deckz.yml` declares
(`studioz.workflows`, its schema in studioz, refusing unknown keys; deckz ignores
the section, which a deckz test keeps): each a form on the workspace page or a deck
page whose answers fill a prompt naming one of the repository's skills, sent to the
conversation like a message; a file given goes into `.run/studioz/fichiers/`. The
home page offers those of the main checkout's `HEAD` (read through git,
`declared_at`), each opening a new workspace from it where the agent starts. A
workflow with `report: true` has the agent write its findings as a Markdown task
list in `.run/studioz/rapports/`, which the sidebar's Rapports panel shows as a
checklist, `then` sending the ticked ones to a follow-up skill. `studioz.backlog`
runs the workspace's `deckz i18n stale --json` again when its HEAD moves, for the
sidebar's "À traduire" panel, each file with "Traduire avec l'agent" and "Rien à
porter…" (the workspace's `deckz i18n mark-synced`: an empty commit whose
`Lang-synced: <path>` trailer settles the pair, which the agent's hook refuses like a
commit); the Commit dialog presets the `Lang-sync` answer of a commit porting only
backlog files.

Its tests are in `studioz/tests/`, driving the app with FastAPI's test client
on a temporary repository, the watches with a fake `deckz` printing the
same log lines, and the agent with a fake Agent SDK client.
