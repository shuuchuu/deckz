from . import app

_AGENT_NOTES = """\
# Working in this repo

This is a `deckz`-managed repository: a set of slide decks that share
slides ("sections") with each other via `content/`: Markdown content files,
converted by pandoc and compiled with Typst. Run `deckz --help`
or `deckz <command> --help` for the full, authoritative command reference
-- these notes only cover conventions that aren't self-documenting there.

## Layout

- `deckz.yml` / `variables.yml` are looked up and merged from the repo
  root, your XDG config dir, and every directory between the repo root and
  wherever you run `deckz` from -- so settings/variables can be overridden
  per company/deck by placing a file deeper in the tree.
- Shared content lives under `content/<section>/<section>.yml` (the
  directory name must match the yml's stem) plus its sibling content
  files (`deckz.yml`'s `file_extensions`, `.md` by default).
- Each deck is `<company>/<deck>/deck.yml`, with its own local `content/`
  directory for deck-specific content and per-file overrides (see below).

## Section/flavor syntax

A `deck.yml`/section `.yml` includes another section with
`$path/to/section@flavor`, or a plain file with `path/to/file` (both
optionally followed by `: Title`). A flavor is a named, ordered list of
includes declared in that section's own `.yml`.

A deck (or a nested section) can override a single file of a shared
section without forking the whole section: if
`<deck>/content/<section>/<file>.md` exists, it's used in place of
`content/<section>/<file>.md` for that deck only -- a local file
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
- `deckz run file PATH` / `deckz run section SECTION FLAVOR` -- preview a
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
- Add `--html` to any `run` command to also build the HTML deck (from
  `templates/jinja2/main.html` and `deckz.yml`'s `html_pandoc_command`),
  packaged under the deck's `html/` directory.
- `deckz clean all` -- wipe every deck's build dir, plus the `.run`
  scratch directory above and `check variables`'/`check content
  --staged`'s `.check` one.

## Checks, lab notebooks and agent-facing output

- `deckz check` (alias `deckz check content`) -- lab notebook IDs valid
  and unique, fr/en lab notebook pairs present and in sync, hands-on
  notebooks with no stored outputs and demos with some, asset credit
  lines free of LaTeX, no raw LaTeX in content, no hand-written link to
  the lab-publishing remote -- plus the repo's own `templates/checks.py`
  checks, merged in under their own names. `--staged` checks the git
  index's staged version of every tracked file instead of the working
  tree (so it matches what's about to be committed, and another
  session's unfinished edits don't block or hide a check).
- `deckz check overflow DECK_DIR` -- a built handout's shrunk-to-fit
  frames, worst first, with their source content file(s). Needs the
  handout already built (`deckz run --handout`).
- `deckz check parity DECK_DIR` (needs the `deckz[parity]` extra) --
  compare a built deck's PDF and HTML slide by slide, needing both
  already built (`deckz run --handout --html`). Writes an HTML report by
  default; `--plain` instead prints a worst-first text report and
  contact sheets, meant for an agent.
- `deckz labs fmt`/`ids`/`outputs`/`check`/`compare`/`missing`/`dump`/
  `publish` operate on `labs/notebooks` (see `deckz labs --help` for
  each). `fmt --check` and `ids --dry-run` report without writing;
  `publish` is for a human to run, never an agent.
- `deckz videos render`/`list`/`publish` (needs `deckz[videos]`: Manim,
  plus `ffmpeg`) operate on `@register_scene` classes under
  `figures/scenes` (see `deckz videos --help`). `publish` is for a human
  to run, never an agent, same as `labs publish`.
- `deckz i18n stale [PATHS...]` -- content files and lab notebooks with
  changes not yet ported to their other-language sibling, computed from
  git history and `Lang-sync` commit trailers alone (no stored marker).
- Most analysis commands above (`check content`, `check variables`, `i18n
  stale`, `search-sections`, ...) take `--plain` for a compact, stable,
  colorless report meant for a script or an agent to parse, and some take
  `--json` for a single parseable payload instead.
- `deckz hooks install` wires up this repo's git hooks (pre-commit,
  commit-msg) and Claude Code hooks (`.claude/settings.json`): denying a
  Bash command that would stage everything or discard another session's
  uncommitted work, checking an edited content file on the spot, and
  flagging a fr/en pair changed on one language side only during the
  session. Respect these: several sessions may share this checkout.

## English variant

Add `--en` to `run`/`check variables` to compile the English variant (and to
`show`/`show paths`/`show variables`/`section-files`/`search-sections` to
inspect it). There
is never a separate English deck or section: it's the same
`deck.yml`/section `.yml`, with any title given as `{fr: ..., en: ...}`
instead of a plain string, and `en/` sibling files for translated bodies.
`--en` is strict: the first missing translation aborts the build. Run
`deckz i18n missing-en` to see every gap without aborting.
"""


@app.command()
def generate_agent_notes() -> None:
    """Print onboarding notes for an AI coding agent working in this repo.

    Prints to stdout so you can redirect it wherever your agent reads
    project notes from, e.g. `deckz generate-agent-notes > CLAUDE.md` or
    `> AGENTS.md`.
    """
    print(_AGENT_NOTES)
