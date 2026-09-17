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
`--show-completion` flags to set up completion for your shell.

## Repository layout

`deckz` expects to run inside a git repository organized like this:

```text
root (git repository)
├── deckz.yml
├── variables.yml
├── templates
│   └── jinja2
│       └── main.tex
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
```

`deckz.yml` files are merged, in order, from the git root, from the user's
config directory (XDG-compliant, e.g.
`$HOME/.config/deckz/deckz.yml` on GNU/Linux), and from the current
directory (and its ancestors up to the git root). Run
`deckz print-settings` to inspect the resolved result.

### `variables.yml`

`variables.yml` files hold the values injected into the Jinja2 templates,
merged the same way (git root → user config directory → current directory
and its ancestors), so a value set closer to a deck overrides one set
higher up. Run `deckz print-variables` to inspect the resolved result for
the current deck.

Example:

```yaml
company_name: Company
company_logo: img/logo.png
company_logo_height: 1cm
deck_title: Machine Learning and COVID-19
presentation_size: 10pt
```

Each `snake_case` key becomes a `\CamelCase` LaTeX command (e.g.
`company_name` → `\CompanyName`) usable from `templates/jinja2/main.tex`
and from any included file.

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
    title: Part 2
    sections:
      - $first-section@light
```

Includes can point to a file (`path/to/file`) or to a shared section with a
given flavor (`$path/to/section@flavor`); either form can be given a custom
title with `path: My title` / `$path@flavor: My title`.

### Shared sections

A shared section lives under `shared/latex` (or a deck's local `latex`
directory) and has a sibling `.yml` file describing its flavors, e.g.
`shared/latex/first-section/first-section.yml`:

```yaml
title: First section
default_titles:
  intro: Introduction
  advanced: Advanced
flavors:
  - name: standard
    includes:
      - intro
      - advanced
  - name: light
    includes:
      - intro
```

## Usage

Run `deckz --help` for the full list of commands, or `deckz <command>
--help` for a specific command. The main ones:

- `deckz run [PARTS]...`: compile the deck in the current directory
  (optionally restricted to some parts).
- `deckz check-all`: compile every shared section standalone, to catch
  errors before they show up in a real deck.
- `deckz watch deck` / `deckz watch section SECTION FLAVOR`: recompile on
  file changes.
- `deckz tree`: show the resolved tree of sections and files for the
  current deck.
- `deckz print-settings` / `deckz print-variables`: print the resolved
  settings/variables for the current directory.
- `deckz deps [SECTION] [FLAVOR]`: show shared sections/flavors usage
  across the repository, including unused ones.
- `deckz search-sections KEYWORDS...`: search shared sections by title or
  frame title.
- `deckz section-flavors SECTION`: list a section's flavor names.
- `deckz rename-flavor SECTION OLD NEW`: rename a flavor and rewrite all
  its usages.
- `deckz merge-flavors`: deduplicate section flavors that are identical up
  to their name.
- `deckz asset-search ASSET` / `deckz asset-deps`: find where an asset is
  used, or find assets missing license metadata.
- `deckz clean` / `deckz clean-all` / `deckz clean-latex`: remove build
  directories, or unused shared/local LaTeX files.
- `deckz upgrade`: migrate a repository from older `deckz` conventions.
- `deckz i18n section-en-leak` / `deckz i18n section-flavor-diff` / `deckz
  i18n section-pair` / `deckz i18n deck-pair`: help keep fr/en translations
  of decks and shared sections in sync.
- `deckz upload`: upload built PDFs to Google Drive.
- `deckz extras issue TITLE [BODY]`: create a GitHub issue.
- `deckz extras random REASON`: roll a dice and email the result (handy for
  arbitrary decision-making, e.g. picking who does a task).

## Documentation

A partial code reference, generated from the docstrings, is published via
`mkdocs` (see `mkdocs.yml` and the `docs` directory).
