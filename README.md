# `deckz`

[![CI Status](https://img.shields.io/github/actions/workflow/status/shuuchuu/deckz/ci.yml?branch=main&label=CI&style=for-the-badge)](https://github.com/shuuchuu/deckz/actions?query=workflow%3ACI)
[![CD Status](https://img.shields.io/github/actions/workflow/status/shuuchuu/deckz/cd.yml?label=CD&style=for-the-badge)](https://github.com/shuuchuu/deckz/actions?query=workflow%3ACD)
[![Test Coverage](https://img.shields.io/codecov/c/github/shuuchuu/deckz?style=for-the-badge)](https://codecov.io/gh/shuuchuu/deckz)
[![PyPI Project](https://img.shields.io/pypi/v/deckz?style=for-the-badge)](https://pypi.org/project/deckz/)

`deckz` is a tool to manage a large number of slide decks (Markdown compiled with Typst), shared by several
people, with slides ("sections") shared across decks. It is not meant to be
usable out of the box by people who stumble upon this repository: it enforces
strong conventions on the layout of the repository it operates on. Please
open an issue if you want more details or want to discuss this approach.

## Installation

With `pip`:

```shell
pip install deckz
```

The side commands `deckz upload` and `deckz extras issue`/`random` need
optional dependencies (Google Drive, GitHub and SendGrid clients):

```shell
pip install "deckz[extras]"
```

Whatever your `templates/assets_builders.py` imports (e.g. matplotlib or
plotly) is your repository's own dependency: install it alongside deckz.

### Shell completion

Run `deckz --help` and look for the `--install-completion` /
`--show-completion` flags to set up completion for your shell
interactively, or run `deckz generate-completion {bash,zsh,fish}` to print
the completion script yourself (e.g. to source from your own dotfiles).

## Repository layout

`deckz` expects to run inside a git repository organized like this:

```text
root (git repository)
├── deckz.yml
├── variables.yml
├── templates
│   ├── assets_builders.py
│   └── jinja2
│       ├── main.typ
│       └── env.py
├── content
│   └── some-section
│       ├── some-section.yml
│       ├── intro.md
│       └── advanced.md
├── assets
│   ├── img
│   ├── plt
│   └── pltly
├── company1
│   ├── variables.yml
│   └── deck1
│       ├── deck.yml
│       ├── variables.yml
│       └── content
└── company2
    └── deck2
        ├── deck.yml
        └── content
```

- `content`: reusable sections (Markdown content files), shared across decks.
- `assets`: everything else shared across decks (images, generated
  figures, or any other kind of asset your own
  `templates/assets_builders.py` produces). `deckz` doesn't know or care
  what subdirectories live under `assets` -- it symlinks every one of them
  into each build directory, so `intro.md` can reference
  `plt/some-figure.svg` the same way regardless of what else is in
  there. The `plt`/`pltly` names above are just this repo's own
  convention, set up by its `templates/assets_builders.py` -- see [Assets
  builders](#assets-builders).
- `templates/jinja2/main.typ`: the Jinja2 template used to render every
  deck's main Typst file.
- `templates/jinja2/env.py`: the Python module that configures the Jinja2
  environment(s) used to render content files -- see [Content files and
  the Jinja2 environment](#content-files-and-the-jinja2-environment).
- `templates/assets_builders.py`: the Python module that builds this
  repo's assets (generated figures, or anything else) -- see [Assets
  builders](#assets-builders).
- Each deck is a directory containing a `deck.yml` (its definition) and
  optionally a `content` directory for files local to that deck.
- `variables.yml` files can be placed at any level of the directory
  hierarchy between the git root and a deck to avoid repeating values
  (e.g. one per client/company, shared by all of that client's decks).

## Configuration

`deckz.yml`, `deck.yml` and section definition files all accept an
optional `schema_version` key, the version of their format (currently and
by default `1`). A future incompatible format change will bump it, so an
older `deckz` rejects a newer file with a clear message instead of
misreading it.

### `deckz.yml`

At the root of the repository, `deckz.yml` holds settings, not content, e.g.:

```yaml
pandoc_command:
  - pandoc
  - -f
  - markdown-auto_identifiers
  - -t
  - typst
  - --lua-filter={templates_dir}/pandoc/filters/boxes.lua
typst_parallel_compilations: 1
typst_font_paths:
  - assets/fonts
typst_ignore_system_fonts: true
```

- `typst_parallel_compilations`: how many PDFs compile at once (default
  1). `deckz` compiles the main Typst file (`paths.jinja2_main_template`)
  with the `typst` Python bindings, each PDF in its own child process,
  which gives its memory back when done (Typst can take a few GB on a large
  deck, and already uses every core within one compilation). Under `deckz
  run --watch`, each PDF's process stays alive instead, so rebuilds are
  incremental: on a 145-page deck, an edit re-renders every PDF in about a
  second.
- `typst_font_paths`: directories where Typst looks for fonts, on top of
  its embedded ones (Libertinus Serif, New Computer Modern, DejaVu Sans
  Mono). Relative to the git root; `{git_dir}`, `{assets_dir}` and
  `{templates_dir}` are substituted too. Defaults to none.
- `typst_ignore_system_fonts`: when true, Typst doesn't use the fonts
  installed on the machine (default false). Together with fonts
  committed under `typst_font_paths`, every author's PDFs then come out
  identical whatever fonts they have installed, and each PDF also skips
  scanning the system's fonts (about 0.2s per PDF with a thousand fonts
  installed).
- `pandoc_command`: how `deckz` invokes `pandoc` to convert a rendered
  Markdown content file to the `.typ` fragment that gets `#include`d,
  including any `--lua-filter=...` your own conventions need (fenced divs
  for admonition boxes, external code-file inclusion, etc.) -- entirely up
  to you, `deckz` has no opinion here. `pandoc` is invoked with a working
  directory matching the
  content fragment's own (possibly nested) position under the build
  directory, so any path an argument needs (e.g. a `--lua-filter`) should be
  written as `{git_dir}` or `{templates_dir}`, substituted with the resolved
  absolute path -- a bare relative path would not resolve consistently.
- `file_extensions`: the extensions tried, in order, when resolving a file
  include. Defaults to `[".md"]`.

`deckz.yml` files are merged, in order, from the git root, from the user's
config directory (XDG-compliant, e.g.
`$HOME/.config/deckz/deckz.yml` on GNU/Linux), and from the current
directory (and its ancestors up to the git root). Run
`deckz show settings` to inspect the resolved result.

### `variables.yml`

`variables.yml` files hold the values injected into the Jinja2 templates,
merged the same way (git root → user config directory → current directory
and its ancestors), so a value set closer to a deck overrides one set
higher up. Run `deckz show variables` to inspect the resolved result for
the current deck.

Example:

```yaml
company_name: Company
company_logo: img/logo.png
company_logo_height: 1cm
deck_title: Machine Learning and COVID-19
presentation_size: 10pt
```

These variables are passed to `templates/jinja2/main.typ`, and to every
content file, as a `variables` mapping; what the templates do with them is up to
your own template and Jinja2 environment, not something `deckz` imposes --
see [Content files and the Jinja2 environment](#content-files-and-the-jinja2-environment).

### `deck.yml`

Defines a deck's parts and, for each part, the sections and files it
includes:

```yaml
name: ABC
parts:
  - name: p1
    title: Part 1
    sections:
      - $first-section@standard
      - about
  - name: p2
    title:
      fr: Partie 2
      en: Part 2
    sections:
      - $first-section@light
```

Includes can point to a file (`path/to/file`) or to a shared section with a
given flavor (`$path/to/section@flavor`); either form can be given a custom
title with `path: My title` / `$path@flavor: My title` (or, as with `p2`'s
title above, a `{fr: ..., en: ...}` map instead of a plain string, when the
text actually differs by language -- see [Titles, variables and
`--en`](#titles-variables-and---en)).

### Shared sections

A shared section lives under `content` (or a deck's local `content`
directory) and has a sibling `.yml` file describing its flavors, e.g.
`content/first-section/first-section.yml`:

```yaml
title: First section
default_titles:
  intro: Introduction
  advanced:
    fr: Approfondissement
    en: Advanced
flavors:
  - name: standard
    includes:
      - intro
      - advanced
  - name: light
    includes:
      - intro
```

### Flavor-level variables

A flavor can also set its own `variables`, merged into the rendering
context of its content (and, cascading down, of every section it includes)
on top of `variables.yml` -- the way to give two flavors of the same
section genuinely different content instead of duplicating the section
itself:

```yaml
title: Keras
variables_to_define:
  - depth: [shallow, deep]
flavors:
  - name: light
    variables: { depth: shallow }
    includes:
      - body
  - name: full
    variables: { depth: deep }
    includes:
      - body
```

`body.md` then reads `{{ variables.depth }}` the same way it would read any
deck-wide variable. `variables_to_define` is a contract, not a default: it
never supplies a value itself, it just declares that every flavor below
must set that key itself (optionally restricted to the given list of
values) -- a flavor missing one, or setting one out of range, fails to
parse. `deckz check variables` statically surveys every shared flavor and
every real deck for two kinds of drift this contract doesn't catch by
itself: a fragment reading a `variables.xxx` name nothing resolved at that
point ever sets, and a declared name no fragment anywhere under its section
ever reads.

### Titles, variables and `--en`

There is only ever one `deck.yml`/section `.yml` -- English is never a
separate deck or a duplicated section, only a `--en` flag on `deckz run`
(and on `deckz check variables`, `deckz show`/`show paths`/`show variables`,
`deckz section-files` and `deckz search-sections`, to inspect the English
variant the same way). Commands that act on the whole repository --
`deckz clean content`, `deckz asset search`, `deckz asset deps` -- always
cover both languages, so an `en/` file counts as used whenever a
`deckz run --en` would pick it:

- Any title (`deck.yml` part/include titles, a section's `title`,
  `default_titles` values, a flavor's title) and any `variables.yml` value
  can be a plain string, used as-is in every language -- the right choice
  whenever the text is language-neutral (a proper noun, a number, code, or
  simply not translated yet) -- or an explicit `{fr: ..., en: ...}` map when
  it actually needs to differ by language, as in `intro`/`advanced` above.
- A translated body file lives at `<parent-dir>/en/<filename>`, a sibling of
  the French file, whatever `parent-dir` is -- a shared section directory, a
  deck's local `content` directory, or any nested subdirectory of either.
  Section/flavor structure itself is never duplicated for English.
- `--en` never silently falls back to French for a `{fr: ..., en: ...}` map
  that's missing its `en` key, or for a resolved file with no `en/` sibling:
  both fail the build immediately, so a translation that was started but
  left incomplete can't accidentally ship untranslated. A plain string, on
  the other hand, is never a gap -- it means "the same in every language" by
  design. `deckz i18n missing-en` audits a deck for both kinds of gap
  (blocking and merely informational) without needing to actually compile it.
- fr and `--en` builds write to separate output paths (an `en/` subdirectory
  under `.build`/`pdf`), so both can be built from the same checkout without
  clobbering each other.

### Content files and the Jinja2 environment

Content files (a section's or a deck's included files) are plain text,
templated with Jinja2, using whatever delimiters and filters
`templates/jinja2/env.py` configures -- `deckz` itself has no opinion on
this beyond providing the mechanism. That module must expose:

```python
from jinja2 import Environment


def environment_for(suffix: str) -> Environment:
    ...
```

called once per content-file suffix `deckz` renders (typically once for
the `.typ` main template, once for `.md` content), so different sources can
use different delimiters/filters. This is also where you define any
macro/filter your content relies on, e.g. an `image` filter emitting
`![](...)`.

Whatever filter you use to reference an asset file (an image, a generated
plot, ...) should call the `assets_metadata_retriever` context
variable `deckz` injects into every render, e.g. from a filter function:

```python
from jinja2 import pass_context
from jinja2.runtime import Context


@pass_context
def image(context: Context, path: str) -> str:
    metadata = context["assets_metadata_retriever"](path)
    ...
```

This is the hook that keeps `deckz asset search`/`deckz asset deps` (and
the i18n tooling) accurate: skip it, and asset usage/licensing detection
silently misses whatever your filter references.

### Assets builders

`deckz` itself has no opinion on what assets a deck needs (generated
figures, or anything else) or how to build them. Your repo supplies a
Python module (`templates/assets_builders.py`) exposing:

```python
from collections.abc import Iterable
from pathlib import Path

from deckz.components.protocols import AssetsBuilderProtocol, CompilerProtocol


def assets_builders(
    assets_dir: Path, compiler: CompilerProtocol
) -> Iterable[AssetsBuilderProtocol]:
    ...
```

called once (by `deckz run`/`deckz run shared`/`deckz run all`/`deckz run
assets`) to obtain every builder to run. Each
builder implements `AssetsBuilderProtocol`:

```python
from collections.abc import Iterable
from pathlib import Path


class MyAssetsBuilder:
    def build_assets(self) -> None:
        ...  # write output files somewhere under assets_dir

    def watched_dirs(self) -> Iterable[Path]:
        ...  # source directories `deckz run assets --watch` should watch
```

`build_assets` should write its output somewhere under `assets_dir` --
`deckz` symlinks every top-level directory found there into every build
directory, without needing to know their names (see [Repository
layout](#repository-layout)). `watched_dirs` only matters for `deckz run
assets --watch`: it tells the watch loop which source directories should
trigger a rebuild.

### Python hooks: contract and trust

`templates/jinja2/env.py` and `templates/assets_builders.py` are plain
Python modules that `deckz` imports and runs: running `deckz` on a
repository executes its code with your permissions, like any build script,
so only use it on repositories you trust. Whatever they import is your
repository's own dependency, to install alongside `deckz`.

`deckz` checks each hook when loading it: the module must import cleanly
and define the expected function, `environment_for` must return a
`jinja2.Environment`, and each object `assets_builders` returns must have
`build_assets` and `watched_dirs` methods. A module may declare which
version of this contract it targets:

```python
DECKZ_HOOKS_VERSION = 1  # the default when left out
```

A future incompatible change to the contract will bump that version, so a
hook written for another one fails to load with a clear message.

### Markdown content and `pandoc`

Content files are authored in Markdown: `deckz` renders each one through
its own Jinja2 environment (see above) and then converts the result to the
`.typ` fragment the main template `#include`s, by shelling out to
`pandoc_command`. Slide conventions your content relies on
(admonition boxes, external code-file inclusion, columns, math, ...) are
entirely up to how you write your Markdown and configure `pandoc_command`
(typically pandoc's own built-ins plus one or more `--lua-filter=...`
pointing at Lua filters you maintain in this repository, e.g. under
`templates/pandoc/`) -- `deckz` only orchestrates the conversion.

### Upgrading from 28.x (LaTeX removal)

`deckz` no longer compiles LaTeX. In a repository still laid out for 28.x:

- `git mv latex content` at the root, and in every deck directory.
- Remove `compiler` and `build_command` from `deckz.yml` (they're now
  ignored), and `file_extensions` if it only lists `.md`.
- The default main template is now `templates/jinja2/main.typ`: a
  `paths.jinja2_main_template` override pointing there can go.
- `deckz clean latex` is now `deckz clean content`.

## Usage

Run `deckz --help` for the full list of commands, or `deckz <command>
--help` for a specific command. Global options go before the command:
`--quiet`/`-q` only logs warnings and errors, `--verbose`/`-v` adds details
such as per-PDF timings and which fragments get re-rendered, and `--debug`
also shows the traceback of a deckz error (as does `DECKZ_DEBUG=1`).

Exit codes: 0 on success, 1 on a deckz error (e.g. a missing flavor or a
failed compile) or on `deckz check variables` findings, 2 on a command-line
usage error.

`deckz check variables`, `deckz search-sections` and `deckz i18n
missing-en` print one tab-separated finding per line, or, with `--json`, a
single JSON array of objects (see each command's `--help` for the fields).

The main commands:

- `deckz run` (alias for `deckz run deck`, optionally restricted with
  `--parts`) / `deckz run file PATH` / `deckz run section SECTION FLAVOR` /
  `deckz run assets`: compile the deck in the current directory, a single
  content file, a specific section flavor, or the project's assets.
  Add `--en` to compile the English variant (see [Titles, variables and
  `--en`](#titles-variables-and---en)), or `--watch` to recompile on file
  changes instead of once. `run file`/`run section` write their output
  under `<git_dir>/.run/`, not the current deck's own `pdf`/`.build`, and
  open it once done (add `--no-open` for agentic/headless use, where only
  the printed path matters).
- `deckz run decks` / `deckz run shared` / `deckz run all`: validate
  the repository by compiling. `run decks` compiles every real deck end to
  end (by far the slowest for a repo with many decks, since every shared
  section gets recompiled once per deck that includes it). `run shared`
  compiles one throwaway deck containing every shared section expanded to
  every file in its directory (not just the ones some named flavor lists) --
  fast enough to run while editing shared content. `run all` does the same
  plus one extra copy of a section for every deck that locally overrides one
  of its files. `--en` is strict: the first gap in translation coverage
  aborts the run. `run shared`/`run all` write their throwaway output
  under `<git_dir>/.run/`.
- `deckz check variables`: statically survey every shared section's every
  named flavor (not just the ones some deck currently uses) plus every real
  deck, resolving `variables` the same way a real build would. Reports a
  fragment reading a `variables.xxx`/`variables['xxx']` name nothing
  resolved at that point sets (`UNDEFINED`), a `variables_to_define` name no
  fragment under its section ever reads (`UNUSED`), a fragment that fails to
  parse (`UNPARSABLE`), and a flavor/deck that fails to parse at all, e.g. a
  `variables_to_define` contract violation (`STRUCTURAL`). Nothing is
  compiled.
- `deckz show` (alias for `deckz show tree`): show the resolved tree of
  sections and files for the current deck.
- `deckz show settings` / `deckz show variables` / `deckz show paths`:
  print the resolved settings/variables/file paths for the current
  directory.
- `deckz deps [SECTION] [FLAVOR]`: show shared sections/flavors usage
  across the repository, including unused ones.
- `deckz search-sections KEYWORDS...`: search shared sections by title or
  Markdown heading.
- `deckz section-flavors SECTION`: list a section's flavor names.
- `deckz section-files SECTION FLAVOR`: list the files a section+flavor
  resolves to.
- `deckz flavor rename SECTION OLD NEW`: rename a flavor and rewrite all
  its usages.
- `deckz flavor deduplicate`: deduplicate section flavors that are identical
  up to their name.
- `deckz asset search ASSET` / `deckz asset deps`: find where an asset is
  used, or find assets missing license metadata.
- `deckz clean` / `deckz clean all` / `deckz clean content`: remove build
  directories, or unused shared/local content files (fr or `en/`). `deckz clean all` also
  removes the whole `<git_dir>/.run/` scratch tree (`run shared`/`run all`/
  `run file`/`run section`), and `<git_dir>/.check/` (`check variables`).
- `deckz i18n missing-en [--all]`: report fr content/titles/variables with no
  English counterpart, i.e. what a `deckz run --en` would currently fail on.
- `deckz generate-agent-notes`: print onboarding notes for an AI coding
  agent working in the repo (conventions not already covered by `--help`,
  e.g. the section/flavor syntax and local-override resolution). Prints to
  stdout, e.g. `deckz generate-agent-notes > CLAUDE.md`.
- `deckz generate-completion {bash,zsh,fish}`: print a shell completion
  script (see [Shell completion](#shell-completion)).
- `deckz upload`: upload built PDFs to Google Drive.
- `deckz extras issue TITLE [BODY]`: create a GitHub issue.
- `deckz extras random REASON`: roll a dice and email the result (handy for
  arbitrary decision-making, e.g. picking who does a task).
- `deckz extras labs NOTEBOOKS...`: normalize Jupyter notebooks (files, or
  directories searched recursively for `*.ipynb`) to this project's Colab
  conventions -- collapse every "Solution" markdown heading cell by
  default, and disable Colab's generative AI features. `--dry-run` lists
  what would change without writing.

## Documentation

A partial code reference, generated from the docstrings, is published via
`mkdocs` (see `mkdocs.yml` and the `docs` directory).
