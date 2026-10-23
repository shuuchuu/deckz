# Foundations

The bottom layers: settings, the deck model, errors and utilities. Every other layer
uses them, and they use nothing above them, except for the
[known exceptions](index.md#known-exceptions).

## `configuring`

| | |
|---|---|
| **Responsibility** | Load and validate `deckz.yml` into settings, and `variables.yml` into a deck's variables |
| **Owns** | `GlobalSettings`, `DeckSettings` and their paths (`GlobalPaths`, `DeckPaths`) |
| **Depends on** | `models`, `utils`, `exceptions` |
| **Never** | Is mutated after construction: a variant (a preview's scratch output) is a copy (`with_output_dirs`) |
| **Entry points** | `GlobalSettings.from_yaml`, `DeckSettings.from_yaml`, [`get_variables`][deckz.configuring.variables] |
| **Fails with** | [`InvalidConfigurationError`][deckz.exceptions.InvalidConfigurationError], `GitRepositoryNotFoundError` |

[`settings`][deckz.configuring.settings] defines Pydantic models. A path field declared
as a template string, such as `"{git_dir}/content"`, is resolved against the fields
computed before it (a `BeforeValidator`, `_convert`/`_Path`). `deckz.yml` is merged from three places, in order: the repository's
root, the user's config directory, then each directory from the root down to the
current one (`utils.dirs_hierarchy`). So a company or a deck can override a setting by
placing a `deckz.yml` deeper in the tree.

| Settings | Scope | Used by |
|---|---|---|
| `GlobalSettings` | The repository | Repository-wide commands: `run decks`, assets, checks, labs, status |
| `DeckSettings` | One deck (the current directory is inside it) | `run [deck]`, `run file`, `show`, `upload` |

[`get_variables`][deckz.configuring.variables] merges the `variables.yml`
files from the repository's root down to the deck. The same variables apply to every
file of a deck, plus `lang`.

## `models`

| | |
|---|---|
| **Responsibility** | The deck domain model: definitions (as parsed from YAML) and the resolved tree |
| **Owns** | `DeckDefinition`, `SectionDefinition`…; `Deck` → `Part` → `Section` → `File`; `ResolvedPath`/`UnresolvedPath`; `Lang`; `CompileResult` |
| **Depends on** | Nothing of deckz |
| **Never** | Reads files or YAML: [`Parser`][deckz.components.parser.Parser] builds the model, and the rest of the code works on the model |

The `Deck` tree is frozen, with tuples of nodes. A transformation (`Deck.filter`, the
synthetic decks of `checking`, `course_notes.chapters_deck`) builds a new tree with
`dataclasses.replace`. A `NodeVisitor` walks a tree. A `ParsedDeck` (from
`utils.all_decks`) is a deck with the variables its files render with, for the analyses
that render content (assets usage).

## `exceptions`

[`DeckzError`][deckz.exceptions] is the base of every error a person can fix.
The CLI turns it into a message and exit code 1. A subclass exists when some code needs
to tell that error apart (to catch it, or to render it like `DeckParsingError`'s tree),
otherwise a plain `DeckzError` with a message naming the fix is enough. `exceptions`
imports `models` only, for the deck a `DeckParsingError` carries.

## `utils`

[`utils`][deckz.utils] holds helpers with no better home: atomic writes, copying a file
only when it changed, `file_lock`, `sync_tree`, YAML loading, finding the git root,
importing a module from a path, the content files of a repository. Its deck parsing
helpers (`parse_deck`, `all_decks`, `all_deck_settings`) belong to a higher layer (see
[Known exceptions](index.md#known-exceptions)). A new helper about one domain goes in
that domain's module, not here.

## `stamps`

[`stamps`][deckz.stamps] decides whether a built file is up to date from a digest of its
inputs' bytes (`<output>.stamp`), never from modification times, which a checkout, a
`git stash` or a copy into a worktree changes. Assets builders and `videos` use it.
Committed outputs come with their stamps, so a fresh clone rebuilds nothing. An
output missing or stale in one checkout is copied from another checkout of the
repository where its stamp matches (`adopt`, which `is_fresh` calls), with the
`companions` a build writes next to it (a video's poster and quality): stamps
digest bytes, never paths, so the copy is what a build here would make. The
checkouts are read from git's own files (`.git`, `commondir`, `worktrees/*/gitdir`),
not by running git: about 0.7 ms per output not fresh here, on slides with five
checkouts.

## `drive_links`

[`drive_links`][deckz.drive_links] reads and writes a deck's registry of Google Drive
links (`paths.drive_links`: `<user config dir>/drive-links/<deck path>.yml`, keyed by
`paths.deck_path`, the deck's directory relative to the repository, so every checkout
shares it): each PDF's path, mapped to the
Drive file `deckz upload --reserve` made for it. Builds read it, through the factory,
to give each PDF its link. Only `deckz upload` reaches Drive.

`Uploader.reserve` creates an empty Drive file for a PDF (or reuses the one already
online) and records it, before any build shows the link. `DeckBuilder._links` gives each
main template `links` (`self`, `handout`, `course_notes`: those the registry has) and
records them next to the build (`.links`). `plan()` reports `links_changed`, which
`pipelines.outdated_pdfs` counts, so a new link rebuilds the PDF. `Uploader.upload`
writes a PDF to its reserved file by ID, and never deletes a reserved file.
