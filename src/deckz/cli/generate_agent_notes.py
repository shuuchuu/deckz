from . import app

_AGENT_NOTES = """\
# Working in this repo

This is a `deckz`-managed repository: a set of slide decks that share
slides ("sections") with each other via `latex/` (a historical name: its
content files may be Markdown, compiled with Typst or LaTeX depending on
`deckz.yml`'s `compiler` and main template). Run `deckz --help`
or `deckz <command> --help` for the full, authoritative command reference
-- these notes only cover conventions that aren't self-documenting there.

## Layout

- `deckz.yml` / `variables.yml` are looked up and merged from the repo
  root, your XDG config dir, and every directory between the repo root and
  wherever you run `deckz` from -- so settings/variables can be overridden
  per company/deck by placing a file deeper in the tree.
- Shared content lives under `latex/<section>/<section>.yml` (the
  directory name must match the yml's stem) plus its sibling content
  files (`deckz.yml`'s `file_extensions`: `.md`, `.tex`).
- Each deck is `<company>/<deck>/deck.yml`, with its own local `latex/`
  directory for deck-specific content and per-file overrides (see below).

## Section/flavor syntax

A `deck.yml`/section `.yml` includes another section with
`$path/to/section@flavor`, or a plain file with `path/to/file` (both
optionally followed by `: Title`). A flavor is a named, ordered list of
includes declared in that section's own `.yml`.

A deck (or a nested section) can override a single file of a shared
section without forking the whole section: if
`<deck>/latex/<section>/<file>.md` exists, it's used in place of
`latex/<section>/<file>.md` for that deck only -- a local file
always wins over a shared one at the same relative path.

A flavor can set its own `variables`, merged into `variables.yml` on top
(cascading down into every section it includes) -- the way to give two
flavors of the same section different content without duplicating the
section. A section's `variables_to_define` is a contract, not a default:
it declares names every flavor below must itself set (optionally
restricted to a fixed list of values), it never supplies a value. Run
`deckz check variables` to find a `variables.xxx` reference nothing sets,
or a declared variable nothing ever reads.

## Commands you'll actually reach for while iterating

- `deckz run` -- compile the current deck (`--parts` to restrict).
- `deckz run file LATEX` / `deckz run section SECTION FLAVOR` -- preview a
  single file or section+flavor standalone, without touching the current
  deck's own build output. Output goes under `<git_dir>/.run/`; add
  `--no-open` to skip opening the result (useful for headless/agent use,
  where the printed output path is all you need).
- `deckz run shared` -- compile every shared section, one PDF per
  section; much faster than `run decks`, which recompiles a section once
  per deck using it.
- `deckz run all` -- `run shared`, plus one extra copy of every
  section that some deck locally overrides.
- `deckz run decks` -- compile every real deck end to end. By far the
  slowest option on a repo with many decks.
- `deckz check variables` -- statically survey every shared flavor and
  every real deck for `variables.xxx` usage gaps, without compiling
  anything.
- Add `--watch` to `run`/`run file`/`run section`/`run assets` to
  recompile on file changes instead of once.
- `deckz clean all` -- wipe every deck's build dir, plus the `.run`
  scratch directory above and `check variables`' `.check` one.

## English variant

Add `--en` to `run`/`check variables` to compile the English variant. There
is never a separate English deck or section: it's the same
`deck.yml`/section `.yml`, with any title given as `{fr: ..., en: ...}`
instead of a plain string, and `en/` sibling files for translated bodies.
`--en` is strict: the first missing translation aborts the build. Run
`deckz i18n missing-en` to see every gap without aborting.
"""


@app.command()
def generate_agent_notes() -> None:
    """Print onboarding notes for an AI coding agent working in this repo.

    Prints to stdout so you can redirect it wherever your agent reads \
    project notes from, e.g. `deckz generate-agent-notes > CLAUDE.md` or \
    `> AGENTS.md`.
    """
    print(_AGENT_NOTES)
