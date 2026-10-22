# Agent hooks plan: worktrees for every agent change, and quick, quiet hooks

## Why

An audit of slides' Claude Code hooks (2026-10-22) found three problems.

- **Other sessions' work.** The Stop hook diffs the whole checkout, and every commit since
  the session started, against a snapshot taken at session start. Several sessions share
  slides' main checkout, so each one is told about the others' edits: in the saved
  transcripts, 486 of the 690 files the 58 Stop reports named (70 %) were never touched by
  the session that got the report.
- **Slow.** Checking one content file runs every check `deckz check` runs, repo-wide (lab
  notebooks, ruff/ty, deck definitions…), and keeps the problems whose text contains the
  file's path. One file takes 10 to 60 s depending on the load; a Stop after another
  session's commit took 23 s for 119 files (its timeout is 30 s), and the post-edit hook
  took 63 s on a loaded machine, past its 60 s timeout. A killed hook records nothing, so
  the next one starts over.
- **Verbose.** A report lists every path (the largest was 20,600 characters). Matching a
  path as a substring attributed `supports/CLAUDE.md`'s problems to `CLAUDE.md` too. A
  one-sided fr/en pair is reported again each time the file changes.

## Decisions

- **An agent changes a repository only from a worktree** when its `deckz.yml` says so
  (`worktree.required_for_agents: true`; slides does). The main checkout is shared by
  every session; a worktree is one session's, so whatever changed in it is that
  session's, and the Stop hook needs no snapshot or attribution. The cost of a worktree
  was measured during studioz's work: `deckz worktree add` takes about 7 s.
- **Enforced as strictly as the hooks can**, in the main checkout:
  - Edit, Write, MultiEdit and NotebookEdit are denied on a file of the main checkout,
    and on a worktree's file from a session still in the main checkout (it must
    `EnterWorktree` first, so that every hook runs where the files are);
  - a Bash command run in the main checkout, or naming one of its paths, must be on a
    read-only allowlist (reading files, git's read-only subcommands, `git merge
    --ff-only` to land a branch, `git worktree`, deckz's read-only commands and `deckz
    worktree`); a redirection into the main checkout is denied;
  - a session starting in the main checkout is told, from the SessionStart hook, to
    create its worktree first.
  A shell command can still write through a program the allowlist trusts (`sed`'s `w`
  command, say): these are guard rails for agents, not a sandbox.
- **A check can run on given files.** A check function may take `paths` (absolute
  paths): it then reports only about those, and returns at once when none is of a kind
  it reads. The hooks pass the files they check; `deckz check` passes nothing and runs
  everything, as before. A check without the parameter (a repository's own, not yet
  adapted) runs in full, as today.
- **Reports name a file's problems by exact path** (`Finding.path`), at most 10 paths
  per list, and a one-sided pair once per session.

## Steps

1. Checks scoping: `paths` on deckz's built-in checks and `ChecksRunner.findings`.
   slides' `tools/checks.py` adds it to its checks.
2. Hooks: the Stop hook diffs a worktree against its base (`git status`, and the commits
   on its branch not on the main checkout's branch), with no snapshot; outside a
   worktree it uses the paths the session's edit tools changed (recorded by the
   post-edit hook, NotebookEdit included). Early exit when nothing changed since the
   last Stop. Pandoc conversions in parallel. Old session state files pruned.
3. The rule: `worktree.required_for_agents`, the pre-edit hook, the Bash allowlist, the
   SessionStart message; `deckz worktree land <name>` to rebase a worktree's branch on
   the main checkout's and fast-forward it.
4. slides: `deckz.yml` sets the flag, `deckz hooks install` rewrites
   `.claude/settings.json`, and `CLAUDE.md`, `HANDBOOK.md` and `docs/decisions.md` say
   it. The running sessions are told before deckz merges, and before slides' flag lands.
