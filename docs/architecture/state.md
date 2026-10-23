# Files and concurrency

deckz keeps no database. Its state is files: in the managed repository (mostly ignored
by git), in the user's config directory, and in git history itself. Several deckz
processes often run at once on one machine: a person's `--watch`, an agent's build in a
worktree, a git hook, studioz's background commands. This page lists who writes what,
and what keeps them from writing it at the same time.

## What deckz writes

| Where | What | Written by | Notes |
|---|---|---|---|
| `<deck>/.build/` | Copied, rendered and converted fragments, rendered main templates, `.render-fingerprint`, `.links`, `.lock` | `DeckBuilder`, `pipelines.deck_lock` | Scratch: `deckz clean` removes it |
| `<deck>/pdf/`, `<deck>/pdf/course-notes/` | The PDFs, with `<main>.markers.json` | `DeckBuilder`, `TypstCompiler` | Stale ones removed by `--sync` |
| `<deck>/html/<name>/` | Packaged HTML decks | `HtmlPackager`, `deck_builder.publish` | |
| `<git_dir>/.run/{file,section,shared,all}/` | Scratch build trees of previews and synthetic decks | `checking.run_scratch_dir`, `preview_settings` | `deckz clean all` |
| `<git_dir>/.run/assets.lock` | The assets lock | `AssetsBuilder` | |
| `<git_dir>/.run/gpu/<machine>/` | A rented GPU machine's state, staged and executed notebooks, notes | `labs.gpu` | `deckz clean all` removes it too, even while a machine runs |
| `<git_dir>/.run/lab-outputs.json` | Cache of notebook output digests | `labs.stale_outputs` | |
| `<git_dir>/.run/studioz/` | studioz's own state for a workspace | studioz | `deckz clean all` removes it too |
| `<git_dir>/.check/{variables,staged}/` | Scratch trees of `check variables`, and the exported index of `check --staged` | `checking.check_scratch_dir`, `export_staged` | `deckz clean all` |
| `<git_dir>/.check/hooks-sessions/` | Per-session state of the Claude Code hooks | `agent_hooks` | |
| `<git common dir>/deckz-bash-snapshots/` | `git status` snapshots around an agent's Bash calls in the main checkout | `agent_checkouts` | |
| Assets (`assets/…`), with `<output>.stamp` | Generated figures, plots, videos | the assets builders, `videos` | Often committed, with their stamps |
| The repository's hooks directory, `.claude/settings.json`, the CI workflow | Installed hooks | `hooks_install` | Only deckz's own hook files or entries |
| `<user config dir>/drive-links/<deck path>.yml` | Each PDF's Google Drive file | `drive_links`, `deckz upload --reserve` | Shared by every checkout |
| `<user config dir>/` | `.env`, credentials (`gdrive-secrets.json`, `gdrive-credentials.pickle`), `github-issues.yml`, `mails.yml` | the user, `extras` | |
| `$XDG_RUNTIME_DIR/deckz/compilation-slots/` | Machine-wide compilation slots | `MachineSlots` | |
| git history | `Lang-sync`, `Lang-synced`, `Lab-outputs-current` trailers, empty commits recording a decision | `commits`, the commit-msg hook | deckz's only state about history |

A new file deckz writes goes in one of these places: `.run/` for a `run` command's
scratch, `.check/` for a check's, the deck's own directories for its outputs, and the
user's config directory for what belongs to the user rather than to a checkout. A new
place gets a row here.

## Freshness

deckz decides what to rebuild from contents, not modification times, because a
checkout, a `git stash`, or a copy into a worktree changes times:

- a fragment is rendered again when its build copy differs from its source
  (`utils.file_changed` on its `build_copy_path`; `needs_render`, the test both `plan`
  and `build_deck` apply), when an output of its rendering is missing, or when the build
  directory's `.render-fingerprint` changed (the converter's command and filters, the
  deck's variables);
- an asset or a video is rebuilt when its stamp doesn't match the digest of its inputs
  (`stamps`), unless another checkout of the repository holds one whose stamp does,
  which is copied instead (`stamps.adopt`);
- a marker record is used while it is at least as new as its PDF.

Every fragment is copied to the build directory before any is rendered. When a render
fails, the copies of the failing fragment and of those not yet rendered are removed: a
copy matching its source would otherwise count as rendered, and the next build would
keep a stale output.

## Locks

Every lock is an `flock` (`utils.file_lock`), which the kernel releases when its
process exits, however it exits.

| Lock | Held by | Serializes |
|---|---|---|
| `<build_dir>/.lock` | `pipelines.deck_lock`, for a target's compilation | Two builds of one deck |
| `<git_dir>/.run/assets.lock` | `AssetsBuilder` | Two runs of the repository's assets builders |
| A compilation slot | `MachineSlots`, for one compilation | All compilations of the machine beyond `typst_machine_compilations` |

Worktrees are the other answer to concurrency: each checkout has its own build
directories, `.run/` and `.check/`, so two sessions in two worktrees share only the
user's config directory and the machine's slots.

## Processes

- Typst compiles in child processes (`components/compiler.py`), kept warm under `--watch`,
  all killed by `compiler.stop()` on Ctrl-C.
- pandoc, git, manim, ffmpeg, ssh and the repository's declared commands run as
  subprocesses.
- Repository-wide analyses that parse every deck (`deck-definitions`, `utils.all_decks`)
  use a process pool (`utils.create_pool`).
- Fragments render in threads inside a deck's build.
