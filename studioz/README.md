# studioz

A local web UI to work on a deckz repository: workspaces (`deckz worktree`), live
previews of the material, editing, committing and syncing, and a Claude agent in
each workspace. It runs on each person's machine, for that person,
and its pages are in French. `studioz-plan.md`, at the root of the deckz repository,
is the plan it follows.

studioz is a member of the uv workspace rooted at the deckz repository, released with
deckz's version. A deckz-managed repository depends on it next to deckz; from that
repository:

```console
uv run studioz
```

starts it on `http://localhost:8421/` and opens the browser (`--port`, `--no-browser`).
It only answers requests naming a local host, and only accepts changes from its own
pages (`studioz.local_only`).

The agent is Claude Code (bundled with the Agent SDK), logged in with the person's own
Claude account: `uv run studioz login` logs it in, once per machine (a `claude`
already logged in counts); studioz never handles credentials, and ignores an
`ANTHROPIC_API_KEY` set in its environment. The
agent edits the workspace's files but never commits nor pushes: the person does, from
studioz.

## Workflows

A repository offers its routine agent work as workflows, in its `deckz.yml`
(deckz ignores the section):

```yaml
studioz:
  workflows:
    - name: Nouvelle formation          # or { fr: ..., en: ... }
      description: Créer une formation à partir de son programme.
      skill: nouvelle-formation         # .claude/skills/<skill>/SKILL.md
      inputs:
        - { name: programme, kind: file, label: Programme, accept: ".pdf,.md" }
        - { name: precisions, kind: long-text, label: Précisions, required: false }
      prompt: "Crée la formation à partir du programme {programme}. {precisions}"
    - name: Relire la formation (QA)
      skill: qa-formation
      scope: deck                       # on a deck's page; `{deck}` is its path
      prompt: "Fais le QA de la formation {deck}."
```

Each is a form, on the workspace page (and, for `scope: deck`, behind a deck page's
"Avec l'agent…"), whose answers fill `prompt`; the agent then receives it with the
instruction to follow `skill`. An input is `text` (one line, the default),
`long-text` or `file` (kept in the workspace's `.run/studioz/fichiers/`, the prompt
getting its path); each is required unless `required: false`. The prompt says what to
work on, never how: that belongs in the skill, which also asks its own questions. A
workspace reads its own `deckz.yml`, so a branch can add a workflow with its skill;
an invalid section, or a skill the workspace lacks, is shown on its page.

The JavaScript it serves is pinned in `package.json` and copied into
`src/studioz/static/vendor/` (CodeMirror as one bundle of what `codemirror.mjs`
exports), which is committed, so that installing studioz needs no
npm: `uv run doit vendor` (at the deckz root) refreshes it after a version change.
