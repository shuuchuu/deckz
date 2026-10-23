# Tasks

The modules just below the command line each back one task a person (or an agent)
does: see where their work stands, set up a clone, start new content, guard a shared
checkout. Each one composes the layers below it and returns plain data (items, sections,
verdicts), which the CLI renders and studioz reads as `--json`.

## Agent hooks

`agent_hooks` sits above `agent_checkouts`. Together they are the top of the core.

| | |
|---|---|
| **Responsibility** | Claude Code hooks: guard rails for agent sessions sharing a checkout |
| **Owns** | Each hook's verdict (allow, deny with a reason, a report to the session) |
| **Depends on** | `agent_checkouts`, `analyzing.i18n_stale` (fr/en pairing), the factories (content checks, `pandoc_command`), [`load_hook`][deckz.components.hooks.load_hook] (the repository's `templates/hooks.py`) |
| **Never** | Is the only guard of a repository rule: the git hooks and CI are |
| **Entry points** | `deckz hooks <event>` (`cli/hooks/`), installed into `.claude/settings.json` by [`install_claude_hooks`][deckz.hooks_install.install_claude_hooks] |
| **Fails with** | Nothing: a hook that fails lets the action through |

[`agent_hooks`][deckz.agent_hooks] handles the events that need no rule about checkouts:

- before a Bash command, it refuses skipping the git hooks, staging everything, and
  discarding uncommitted changes;
- after an edit, it converts the edited content file and runs the content checks on it
  alone;
- on Stop, it flags a fr/en pair changed on one side only.

[`agent_checkouts`][deckz.agent_checkouts] holds the rule that an agent changes a
repository only from its own worktree (`deckz.yml`'s `worktree.required_for_agents`).
It refuses edits and commands that change the main checkout, reports what a command
changed there anyway, and maps Claude Code's worktrees onto `deckz worktree`'s.

These hooks are for the risks only agents create. Every repository rule they apply is
also applied by a git hook or a check, which every contributor passes.

## `status`

| | |
|---|---|
| **Responsibility** | Where a person's work stands, and what is left to do, each item with its fix |
| **Owns** | `StatusSection`/`StatusItem` (sections told apart by their `key`); "your changes" (`base_revision`, `changed_paths`) |
| **Depends on** | `pipelines` (what is outdated), `analyzing` (checks, i18n, affected decks, overflow), `labs`, `videos`, the factories |
| **Never** | Touches the network unless `fetch` |
| **Entry points** | [`status`][deckz.status.status], [`deck_status`][deckz.status.deck_status] (`deckz status [DECK]`) |
| **Fails with** | `DeckzError` from what it reads (settings, git) |

studioz's Problems panel is `deckz status --json --no-decks`, so the JSON shape of a
section is a contract with studioz (see [studioz](studioz.md)).

## `setting_up`

| | |
|---|---|
| **Responsibility** | Set up a clone: every step idempotent, `check=True` changes nothing |
| **Owns** | `SetupItem` (`ok`, `done`, `missing`, `failed`, with its fix) |
| **Depends on** | `hooks_install`, `videos` (renders a build needs), `deckz.yml`'s `setup.requires`/`setup.steps` |
| **Never** | Fails half-way silently: each step reports its own item |
| **Entry points** | [`setup`][deckz.setting_up.setup] (`deckz setup`), [`incomplete`][deckz.setting_up.incomplete] |
| **Fails with** | Items with status `failed`, the CLI exiting 1 |

## `scaffolding`

| | |
|---|---|
| **Responsibility** | The files a new deck, shared section or lab notebook pair needs, in both languages |
| **Owns** | Nothing it didn't create: it refuses to overwrite |
| **Depends on** | `labs` (IDs, notebook format), the repository's `templates/scaffold/` |
| **Entry points** | `deckz new deck`, `deckz new section`, `deckz labs new` |
| **Fails with** | [`ScaffoldRefusedError`][deckz.exceptions.ScaffoldRefusedError] |

## `ci_report`

| | |
|---|---|
| **Responsibility** | Turn a scheduled CI run's failures into one GitHub issue (or a comment on the open one) |
| **Depends on** | `exceptions` only; GitHub's API through `urllib`, with the job's `GITHUB_TOKEN` |
| **Entry points** | `deckz hooks ci-report` |

## `hooks_install`

`hooks_install` is in a lower layer (with `labs` and `videos`), since `setting_up` uses
it.

| | |
|---|---|
| **Responsibility** | Write deckz's git hooks, its Claude Code hooks and its CI workflow into a managed repository |
| **Owns** | The `pre-commit` and `commit-msg` hook files that carry deckz's marker line; deckz's own entries in `.claude/settings.json`; the CI workflow file |
| **Never** | Overwrites a hook file deckz didn't write, unless `--force` |
| **Entry points** | `deckz hooks install [--ci]`, `deckz setup` |
| **Fails with** | [`HookInstallRefusedError`][deckz.exceptions.HookInstallRefusedError] |

Every hook it installs is a thin script that runs `deckz` again (`deckz_command`: from
the `PATH`, else `uv run --quiet deckz`), so the rules stay in deckz:

- `pre-commit` runs `deckz check --staged`, the checks on the staged tree only (see
  [Analyses and checks](analyzing.md#content-checks));
- `commit-msg` runs `deckz hooks check-commit-msg`, which marks a commit changing one
  side of a fr/en pair `Lang-sync: pending`;
- the CI workflow runs the same checks, plus `deckz hooks check-commits`.
