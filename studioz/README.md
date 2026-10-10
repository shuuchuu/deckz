# studioz

A local web UI to work on a deckz repository: workspaces (`deckz worktree`), live
previews of the material, editing, committing and syncing, and, later, Claude agents
running the repository's skills. It runs on each person's machine, for that person,
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

The JavaScript it serves is pinned in `package.json` and copied into
`src/studioz/static/vendor/`, which is committed, so that installing studioz needs no
npm: `uv run doit vendor` (at the deckz root) refreshes it after a version change.
