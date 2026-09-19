# `deckz`

[![CI Status](https://img.shields.io/github/actions/workflow/status/shuuchuu/deckz/ci.yml?branch=main&label=CI&style=for-the-badge)](https://github.com/shuuchuu/deckz/actions?query=workflow%3ACI)
[![CD Status](https://img.shields.io/github/actions/workflow/status/shuuchuu/deckz/cd.yml?label=CD&style=for-the-badge)](https://github.com/shuuchuu/deckz/actions?query=workflow%3ACD)
[![Test Coverage](https://img.shields.io/codecov/c/github/shuuchuu/deckz?style=for-the-badge)](https://codecov.io/gh/shuuchuu/deckz)
[![PyPI Project](https://img.shields.io/pypi/v/deckz?style=for-the-badge)](https://pypi.org/project/deckz/)

`deckz` is a tool to manage a large number of Beamer decks, shared by several
people, with slides ("sections") shared across decks. It is not meant to be
usable out of the box by people who stumble upon this repository: it enforces
strong conventions on the layout of the repository it operates on. Please
open an issue if you want more details or want to discuss this approach.

## Installation

With `pip`:

```shell
pip install deckz
```

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
│   └── jinja2
│       ├── main.tex
│       └── env.py
├── shared
│   ├── img
│   ├── code
│   ├── latex
│   │   └── some-section
│   │       ├── some-section.yml
│   │       ├── intro.tex
│   │       └── advanced.tex
│   ├── tikz
│   ├── plt
│   └── pltly
├── company1
│   ├── variables.yml
│   └── deck1
│       ├── deck.yml
│       ├── variables.yml
│       └── latex
└── company2
    └── deck2
        ├── deck.yml
        └── latex
```

- `shared`: everything shared across decks: images and code snippets
  (`img`, `code`), reusable LaTeX sections (`latex`), and generated
  standalone figures (`tikz`, `plt` for matplotlib, `pltly` for plotly).
- `templates/jinja2/main.tex`: the Jinja2 template used to render every
  deck's main `.tex` file.
- `templates/jinja2/env.py`: the Python module that configures the Jinja2
  environment(s) used to render content files -- see [Content files and
  the Jinja2 environment](#content-files-and-the-jinja2-environment).
- Each deck is a directory containing a `deck.yml` (its definition) and
  optionally a `latex` directory for files local to that deck.
- `variables.yml` files can be placed at any level of the directory
  hierarchy between the git root and a deck to avoid repeating values
  (e.g. one per client/company, shared by all of that client's decks).

## Configuration

### `deckz.yml`

At the root of the repository, `deckz.yml` holds settings, not content, e.g.:

```yaml
build_command:
  - latexmk
  - -pdflatex=xelatex -shell-escape -interaction=nonstopmode %O %S
  - -dvi-
  - -ps-
  - -pdf
pandoc_command:
  - pandoc
  - -f
  - markdown
  - -t
  - beamer
  - --slide-level=1
  - --lua-filter={git_dir}/templates/pandoc/filters/boxes.lua
file_extensions:
  - .md
  - .tex
```

- `pandoc_command`: how `deckz` invokes `pandoc` to convert a rendered
  Markdown content file to the `.tex` fragment that gets `\input`, including
  any `--lua-filter=...` your own Beamer conventions need (fenced divs for
  admonition boxes, external code-file inclusion, etc.) -- entirely up to
  you, `deckz` has no opinion here. Only needed if any content is authored
  in Markdown. `pandoc` is invoked with a working directory matching the
  content fragment's own (possibly nested) position under the build
  directory, so any path an argument needs (e.g. a `--lua-filter`) should be
  written as `{git_dir}` or `{templates_dir}`, substituted with the resolved
  absolute path -- a bare relative path would not resolve consistently.
- `file_extensions`: the extensions tried, in order, when resolving a file
  include. Defaults to `[".tex"]`; a repository migrating content to
  Markdown sets `[".md", ".tex"]` so a file is picked up as Markdown if
  present, falling back to a legacy `.tex` sibling otherwise -- letting the
  two coexist during a section-by-section migration.

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

These variables are passed to `templates/jinja2/main.tex` as a `variables`
mapping; what `main.tex` does with them (e.g. turning each `snake_case` key
into a `\CamelCase` LaTeX command usable from any included file) is up to
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

A shared section lives under `shared/latex` (or a deck's local `latex`
directory) and has a sibling `.yml` file describing its flavors, e.g.
`shared/latex/first-section/first-section.yml`:

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

### Titles, variables and `--en`

There is only ever one `deck.yml`/section `.yml` -- English is never a
separate deck or a duplicated section, only a `--en` flag on `deckz run` (and
`deckz check`/`deckz watch`):

- Any title (`deck.yml` part/include titles, a section's `title`,
  `default_titles` values, a flavor's title) and any `variables.yml` value
  can be a plain string, used as-is in every language -- the right choice
  whenever the text is language-neutral (a proper noun, a number, code, or
  simply not translated yet) -- or an explicit `{fr: ..., en: ...}` map when
  it actually needs to differ by language, as in `intro`/`advanced` above.
- A translated body file lives at `<parent-dir>/en/<filename>`, a sibling of
  the French file, whatever `parent-dir` is -- a shared section directory, a
  deck's local `latex` directory, or any nested subdirectory of either.
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
`.tex`, once for `.md` if you author some content in Markdown), so
different sources can use different delimiters/filters -- e.g. the
LaTeX-escaped delimiters `\V{...}`/`\BLOCK{...}`/`%%` traditionally used
for `.tex` (to avoid clashing with LaTeX's own `{`/`}`/`%`) don't need to
carry over to `.md`, where plain `{{ ... }}`/`{% ... %}` read just as well.
This is also where you define any macro/filter your content relies on, e.g.
an `image` filter emitting `\includegraphics{...}` (for `.tex`) or
`![](...)` (for `.md`).

Whatever filter you use to reference an asset file (an image, a tikz/plot
standalone, ...) should call the `assets_metadata_retriever` context
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

### Markdown content and `pandoc`

A content file can be authored in Markdown instead of LaTeX: with
`.md` listed in `file_extensions` (see `deckz.yml` above), `deckz` renders
it through its own Jinja2 environment (see above) and then converts the
result to the `.tex` fragment that gets `\input`ed, by shelling out to
`pandoc_command`. Beamer-specific conventions your content relies on
(admonition boxes, external code-file inclusion, columns, math, ...) are
entirely up to how you write your Markdown and configure `pandoc_command`
(typically pandoc's own built-ins plus one or more `--lua-filter=...`
pointing at Lua filters you maintain in this repository, e.g. under
`templates/pandoc/`) -- `deckz` only orchestrates the conversion, the same
way it only orchestrates LaTeX compilation via `build_command`.

## Usage

Run `deckz --help` for the full list of commands, or `deckz <command>
--help` for a specific command. The main ones:

- `deckz run` (alias for `deckz run deck`, optionally restricted with
  `--parts`) / `deckz run file LATEX` / `deckz run section SECTION FLAVOR`:
  compile the deck in the current directory, a single LaTeX file, or a
  specific section flavor. Add `--en` to compile the English variant (see
  [Titles, variables and `--en`](#titles-variables-and---en)). `run file`/
  `run section` write their output under `<git_dir>/.run/`, not the current
  deck's own `pdf`/`.build`, and open it once done (add `--no-open` for
  agentic/headless use, where only the printed path matters).
- `deckz check decks` / `deckz check shared` / `deckz check all`: validate
  the repository by compiling. `check decks` compiles every real deck end to
  end (by far the slowest for a repo with many decks, since every shared
  section gets recompiled once per deck that includes it). `check shared`
  compiles one throwaway deck containing every shared section expanded to
  every file in its directory (not just the ones some named flavor lists) --
  fast enough to run while editing shared content. `check all` does the same
  plus one extra copy of a section for every deck that locally overrides one
  of its files. `--en` is strict: the first gap in translation coverage
  aborts the run. `check shared`/`check all` write their throwaway output
  under `<git_dir>/.check/`.
- `deckz watch deck` / `deckz watch section SECTION FLAVOR`: recompile on
  file changes. Both also accept `--en`.
- `deckz show` (alias for `deckz show tree`): show the resolved tree of
  sections and files for the current deck.
- `deckz show settings` / `deckz show variables` / `deckz show paths`:
  print the resolved settings/variables/file paths for the current
  directory.
- `deckz deps [SECTION] [FLAVOR]`: show shared sections/flavors usage
  across the repository, including unused ones.
- `deckz search-sections KEYWORDS...`: search shared sections by title or
  frame title.
- `deckz section-flavors SECTION`: list a section's flavor names.
- `deckz section-files SECTION FLAVOR`: list the files a section+flavor
  resolves to.
- `deckz flavor rename SECTION OLD NEW`: rename a flavor and rewrite all
  its usages.
- `deckz flavor deduplicate`: deduplicate section flavors that are identical
  up to their name.
- `deckz asset search ASSET` / `deckz asset deps`: find where an asset is
  used, or find assets missing license metadata.
- `deckz clean` / `deckz clean all` / `deckz clean latex`: remove build
  directories, or unused shared/local LaTeX files. `deckz clean all` also
  removes any `check shared`/`check all` scratch directory under
  `<git_dir>/.check/`, and the `run file`/`run section` scratch directory
  under `<git_dir>/.run/`.
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
