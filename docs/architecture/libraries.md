# Domain libraries

Below the analyses are libraries for the domains deckz manages besides decks: lab
notebooks, videos, side services, worktrees, commit trailers and publish remotes. Each library is plain
code, with no dependency on the build pipeline. Several of them shell out (to `git`,
`ssh`, `manim`, `ffmpeg`) or call a remote service, and their optional dependencies are
deckz's extras.

## `labs`

| | |
|---|---|
| **Responsibility** | Lab notebooks: format, IDs, fr/en comparison, execution (local, container, rented GPU), outputs, secrets, publishing |
| **Owns** | The notebooks' canonical JSON form (`notebook.canonical_dump`); `labs/published/`'s assembly; the GPU machines' state in `.run/gpu/<name>/` |
| **Depends on** | `configuring`, `commits` (`Lab-outputs-current`), `worktrees` (a GPU pass), `upstream` and `remotes` (publishing), `extras` (optional imports), `exceptions` |
| **Never** | Imports `analyzing` or `pipelines`: `analyzing.content_checks` uses `labs`, not the reverse |
| **Fails with** | `LabIdConflictError`, `LabContainerError`, `LabPublishRefusedError`, `LabOutputsMismatchError`, `LabOutputsHookError`, `GpuRunError` |

| Module | What it does |
|---|---|
| [`notebook`][deckz.labs.notebook] | Read and edit notebooks without churning their JSON; `pair` finds a notebook's other language |
| [`normalize`][deckz.labs.normalize], [`ids`][deckz.labs.ids], [`inspecting`][deckz.labs.inspecting], [`comparison`][deckz.labs.comparison] | Colab conventions, lab IDs, read-only views, fr/en comparison |
| [`execution`][deckz.labs.execution], [`container`][deckz.labs.container] | Run a notebook's cells in a scratch directory, or in the published repository's dev container |
| [`gpu`][deckz.labs.gpu], [`gpu_pass`][deckz.labs.gpu_pass] | Rent a GPU machine (`GpuBackend`, `VastBackend`), run notebooks there as Colab would, destroy it |
| [`outputs`][deckz.labs.outputs], [`stale_outputs`][deckz.labs.stale_outputs], [`images`][deckz.labs.images] | Write executed outputs back, and find demos whose code changed since |
| [`secrets`][deckz.labs.secrets] | What looks like a credential (a blocking check, and `labs publish`'s refusal) |
| [`publishing`][deckz.labs.publishing] | Force-push one parentless commit of the published notebooks to the labs remote, refusing to drop a published ID |

## `videos`

| | |
|---|---|
| **Responsibility** | Discover `@register_scene` Manim scenes, render them and their posters, publish the renders |
| **Owns** | The renders under `assets/videos/` and their stamps |
| **Depends on** | `stamps`, `remotes` (publishing), `components.protocols`/`progress` (progress reporting), `configuring`, `utils` |
| **Never** | Imports Manim to discover or list scenes: only rendering needs `deckz[videos]`, and it shells out to `manim`/`ffmpeg` |
| **Fails with** | `VideoSceneError`, `VideoFetchError`, `VideoPublishRefusedError` |

`deckz.videos` (`register_scene`, `video_file`, `quality`…) is imported by the managed
repository's scenes and templates (see [plugins](plugins.md)).

## `extras`

| | |
|---|---|
| **Responsibility** | Side services: Google Drive uploads ([`Uploader`][deckz.extras.uploading.Uploader], `deckz upload`), GitHub issues (`github_querying`, `deckz extras issue`), mailing (`mailing`, `deckz extras random`) |
| **Owns** | The Drive files `deckz upload --reserve` creates (with `drive_links`), the user's credentials files in the config directory |
| **Depends on** | `configuring`, `models`, `utils`, `exceptions`; the `deckz[extras]` dependencies |
| **Never** | Is imported at module level outside `cli/extras/`, `cli/upload.py` and the optional parts of `labs`/`analyzing`. Those import it inside [`extras_imports`][deckz.extras.extras_imports], which turns a missing optional dependency into a `MissingExtraError` naming the extra to install |

`extras.uploading` draws its own progress bars with `rich`, an exception to the
`terminal` contract (see [Known exceptions](index.md#known-exceptions)).

## `worktrees`

| | |
|---|---|
| **Responsibility** | Worktrees as workspaces: add (seeded with the main checkout's builds), list, land (rebase, fast-forward), remove |
| **Owns** | `../<repo>--<name>` checkouts on `ws/<name>` branches |
| **Depends on** | `configuring` (`worktree.seed`), `exceptions` |
| **Never** | Removes a worktree holding work found nowhere else |
| **Entry points** | `deckz worktree …`, `agent_checkouts`, `labs.gpu_pass`, studioz's workspaces |
| **Fails with** | [`WorktreeError`][deckz.exceptions.WorktreeError] |

## `commits`

[`commits`][deckz.commits] reads and writes commit trailers (`Lang-sync`,
`Lang-synced`, `Lab-outputs-current`) and makes the empty commits that record a
decision. deckz keeps no state of its own about history: what a commit settles is in its
message.

## `upstream`

| | |
|---|---|
| **Responsibility** | The branch every checkout's work meets on, which `labs publish` and `videos publish` publish from: the main checkout's branch's upstream (`origin/main`), fetched, whichever checkout runs them |
| **Owns** | `Source` (the commit published, and how to name it), what HEAD has that it lacks (`unpushed`) and lacks that it has (`missing`), every version its history holds under some paths (`known_blobs`) |
| **Depends on** | `worktrees` (`main_checkout`), `exceptions`; `git`, with the user's own credentials |
| **Never** | Publishes, pushes or moves a branch: it fetches and reads |
| **Entry points** | `labs.publishing` (`known_blobs`), `deckz labs publish`/`videos publish`, `status` (the Labs section compares the upstream's notebooks) |
| **Fails with** | [`RemoteError`][deckz.exceptions] when the fetch fails |

## `remotes`

| | |
|---|---|
| **Responsibility** | The git remotes `labs publish` and `videos publish` push to: their lookup, fetching a published branch, the force-push |
| **Owns** | The fix for a missing remote (`add_remote_fix`, with its URL from `deckz.yml`'s `setup.remotes`) |
| **Depends on** | `exceptions` only; `git`, with the user's own credentials |
| **Entry points** | `labs.publishing`, `videos.publishing`, `deckz labs publish`/`videos publish` (`require_remotes`), `setting_up` (which runs `git remote add` itself), `status` (reports a missing one) |
| **Fails with** | [`RemoteError`][deckz.exceptions], carrying git's stderr and the fix |
