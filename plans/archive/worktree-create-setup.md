# Handoff: a machine without the videos' tools can't create agent worktrees

Found 2026-10-27 in a slides session; not started. For whoever fixes it.

## Status (2026-10-28)

Fixed as proposed: `SetupItem.shared` marks the items about the machine or what every
checkout shares (deckz's checkout, requirements, remotes, videos, builds set aside),
`incomplete(items, shared=False)` leaves them out, and `create_worktree` (the
WorktreeCreate hook) and `deckz worktree add` fail only on the rest (a failed step, the
git hooks). The hook prints the shared ones as warnings on stderr; `worktree add`
lists them and exits 0. The error on a real failure now names the problem, how to
enter the worktree anyway, and `deckz worktree remove <name>`. Tried on slides (no
xelatex here): exit 0, the path on stdout, both warnings on stderr.

Left:

- **The agent doesn't see the warnings.** Claude Code's hooks reference: "Claude
  never sees stderr from a hook that exits 0", and a WorktreeCreate hook's JSON
  `systemMessage` is discarded. Passing them on would take another hook (e.g.
  PostToolUse on EnterWorktree reading a note the WorktreeCreate hook left). Low
  stakes: `deckz setup` and a failing video render say the same.
- **studioz's workspaces** (`studioz.workspaces.Created.ready`) still count every
  item, so a machine without xelatex gets the "setup incomplete" page and a workflow
  doesn't start. Following would be `incomplete(self.setup, shared=False)`, with the
  shared items shown without blocking.
- The first "Also" below (`setup --check` and steps without `creates`) is untouched.

## Symptom

On a machine without `xelatex` and `dvisvgm`, every EnterWorktree with a name (and
`claude --worktree <name>`, and a subagent's worktree isolation) fails in slides:

```
WorktreeCreate hook failed: … deckz hooks worktree-create: `deckz setup` left
something missing in /home/mog/repos/shuuchuu/slides--qa-formation-design
```

The worktree is made anyway (`git worktree list` shows it, branch `ws/<name>`, builds
seeded, `uv sync` done), but Claude Code takes the hook's exit code 1 as a failed
creation and leaves the session in the main checkout. Workaround: EnterWorktree with
the `path` of the half-made worktree (or the same `name` again, which takes the reuse
path of 68af4ed and skips setup).

`deckz setup --check` in that worktree showed what was missing:

```
missing xelatex   needed for the videos' math (figures/scenes/lesson.py's TeX template)
missing dvisvgm   needed for the videos' math (manim converts xelatex's output with it)
missing Python environment (uv sync)   run `deckz setup` (uv sync)
```

The `uv sync` line is a `--check` artefact (see "Also" below): a plain `uv sync`
there was a no-op. So the two video tools alone made the creation fail.

## Cause

`agent_checkouts.create_worktree` (`src/deckz/agent_checkouts.py`, ~l. 683) raises
`WorktreeError` as soon as `setting_up.incomplete(setup(...))`, and `incomplete` is
true for any item `MISSING` or `FAILED`. Most of `setup`'s items are about the
machine or the shared repository, not about the new worktree, and a worktree can't
fix any of them:

| Item (`setting_up.setup`) | Can be `MISSING` because | Worktree-specific? |
| --- | --- | --- |
| `deckz_checkout` | `../deckz` behind its upstream | no: shared checkout |
| `requirements` | a `setup.requires` command not on the `PATH` (here xelatex, dvisvgm) | no: the machine |
| `git_hooks` | hooks not installed | yes |
| `remotes` | a `setup.remotes` remote missing | no: shared git config |
| `steps` | a step that failed (`uv sync`, `doit web`) | yes |
| `rendered_videos` | a video never rendered anywhere | no: same in every checkout |
| `set_aside_builds` | — | yes |

So the same machine-wide gap blocks every worktree, for every agent, until a human
installs a TeX distribution that only video rendering needs. The other "no" rows have
the same failure in waiting: `../deckz` one commit behind its upstream, or one scene
never rendered, would block agent worktrees just as well.

`cli/worktree/add.py` has the same `incomplete` → exit 1, but there it's only a report
to a person; in the hook it's fatal.

## Proposed fix

- `create_worktree` fails only on the items a worktree needs to work: its steps
  (`FAILED`) and its git hooks. The others (`deckz`, requirements, remotes, videos) are
  printed to stderr as warnings (the hook already redirects stdout there), so the
  agent sees them, and the worktree is returned.
- Simplest shape: a helper in `setting_up` (e.g. `blocks_worktree(items)` or an
  `incomplete(items, scope=...)`) rather than filtering by item label in
  `agent_checkouts`; `SetupItem` may need a field saying what it's about (machine,
  repository, checkout).
- Decide whether `deckz worktree add` (the CLI) follows: probably yes, exit 0 with the
  warnings printed, so a person and an agent get the same verdict.
- Optional, separate: a `setup.requires` entry could say which features need it (videos
  here), so `deckz setup` reports xelatex as "needed for rendering videos" without
  ranking it with pandoc. Not needed for the fix.

## Also (smaller, same area)

- `setting_up.steps(check=True)` reports every step without `creates` as `MISSING`
  ("run `deckz setup`"), so `deckz setup --check` always shows slides' `uv sync` as
  missing, even right after a successful setup. Either give `uv sync` a `creates`
  (`.venv`) in slides' `deckz.yml`, or report a step without `creates` as "not
  checked" rather than missing.
- On failure the half-made worktree stays. With the fix above that should be rare (a
  failed step); when it happens, the error could say how to enter it anyway
  (EnterWorktree with its `path`) or `deckz worktree remove <name>`.

## Tests

`tests/test_agent_checkouts.py` has `test_create_worktree_makes_a_deckz_worktree` and
`…_reuses_an_existing_one` (via `_settings(main, required=False)`). Add: a
`setup.requires` command absent from the `PATH` → the worktree is created and the
warning names it; a failing step → `WorktreeError`, as today.

## Done when

- In slides, on a machine without xelatex, EnterWorktree with a name succeeds and the
  session lands in the new worktree, with the xelatex/dvisvgm warning visible.
- `docs/architecture/` (where it describes `agent_checkouts` and `setting_up`) and
  `create_worktree`'s docstring say which setup items block a worktree.
- Following deckz's CLAUDE.md: change it in a `../deckz-<topic>` worktree, try it on
  slides, tell the running slides sessions before merging (it changes the hook's
  verdict).
