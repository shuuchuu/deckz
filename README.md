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

`deckz labs outputs`' image recompression needs Pillow
(`pip install "deckz[labs]"`, lazily required only when a notebook has a
large image output to shrink); `deckz check parity` needs Playwright and
pypdfium2 (`pip install "deckz[parity]"`, then `playwright install
chromium`).

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
│   ├── checks.py
│   └── jinja2
│       ├── main.typ
│       ├── main.html
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
- `templates/jinja2/main.html`: optional, the Jinja2 template of every
  deck's HTML page, for `--html` builds -- see [HTML
  output](#html-output).
- `templates/jinja2/env.py`: the Python module that configures the Jinja2
  environment(s) used to render content files -- see [Content files and
  the Jinja2 environment](#content-files-and-the-jinja2-environment).
- `templates/assets_builders.py`: the Python module that builds this
  repo's assets (generated figures, or anything else) -- see [Assets
  builders](#assets-builders).
- `templates/checks.py`: optional, the Python module adding this repo's
  own `deckz check` checks -- see [Content checks
  plugin](#content-checks-plugin).
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
- `html_pandoc_command`: the same as `pandoc_command`, for `--html`
  builds: converts each content file to an `.html` fragment instead (see
  [HTML output](#html-output)). Defaults to none, and `--html` then fails.
- `html_static_dirs`: directories of `assets` copied whole into every
  HTML output, on top of the files its page references, for files only
  scripts load (e.g. a math renderer's fonts). Defaults to none.
- `overflow_marker_label`: the Typst metadata label (default
  `formation-overflow`) `deckz check overflow` queries for shrunk-to-fit
  frames (`ratio`/`page` keys) -- only the label's name, the shrinking
  mechanism itself stays your theme's.
- `file_extensions`: the extensions tried, in order, when resolving a file
  include. Defaults to `[".md"]`.
- `labs`: settings for the `deckz labs` commands, e.g.:

  ```yaml
  labs:
    id_metadata_key: shuuchuu.id
    id_pattern: '[a-z0-9]+(-[a-z0-9]+)*'
    publish_remote: labs
    publish_branch: main
    solution_heading: Solution
  ```

  - `id_metadata_key`: dotted path, under a notebook's own `metadata`, of
    its published ID (default `shuuchuu.id`).
  - `id_pattern`: regex a notebook's published ID must fully match
    (default `[a-z0-9]+(-[a-z0-9]+)*`).
  - `publish_remote` / `publish_branch`: the git remote and branch
    `deckz labs publish` force-pushes the published notebooks to (default
    `labs`/`main`).
  - `solution_heading`: the markdown heading text (case-insensitive)
    marking a notebook's collapsed answer cells (default `Solution`).

  The notebooks directory itself (default `{git_dir}/labs/notebooks`) is
  `paths.labs_notebooks_dir`, set like any other path under `paths:`.

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
  design. `deckz i18n missing-en` audits a deck for the blocking gaps
  (and, with `--untranslated`, the merely informational plain strings)
  without needing to actually compile it.
- fr and `--en` builds write to separate output paths (an `en/` subdirectory
  under `.build`/`pdf`/`html`), so both can be built from the same checkout without
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

`deckz` ships one ready-made builder, `TypstFiguresAssetsBuilder`
(`deckz.components.typst_figures_builder`), for a Typst-themed repo whose
figures are Typst sources compiled to SVG: wire it into your own
`assets_builders()` alongside any other builder you need.

### Content checks plugin

`deckz check` (alias for `deckz check content`) runs a few generic content
checks of its own (lab notebook IDs and fr/en pairs, asset credit lines
free of LaTeX, no raw LaTeX in content -- see [Usage](#usage)). A repo can
add its own, theme- or content-specific checks (e.g. a slide frame
pattern your Markdown conventions enforce) from an optional
`templates/checks.py` module exposing:

```python
from collections.abc import Callable, Mapping

from deckz.configuring.settings import GlobalSettings


def checks(settings: GlobalSettings) -> Mapping[str, Callable[[], list[str]]]:
    ...
```

called once, with the repository's settings, to obtain every extra check
to run, each a zero-argument callable returning its problems (empty if
none) the same way deckz's built-in checks do. A name colliding with a
built-in check's is rejected.

### Claude Code hooks

`deckz hooks install` also adds deckz's own Claude Code hooks to
`.claude/settings.json` (Claude Code is treated as a requirement of a
deckz-managed repository, like git): `deckz hooks pre-bash`/`post-edit`/
`session-start`/`stop`, backed by `deckz.agent_hooks`. The generic rules
they enforce need no repo-specific knowledge:

- **PreToolUse/Bash**: deny staging everything (`git add -A`/`.`/`-u`),
  `git commit -a`, `git clean` without `--dry-run`, and anything that
  would discard uncommitted changes (`git checkout`/`restore` on a
  changed file, `git reset --hard`, a bare `git stash`) -- several Claude
  Code sessions may share one checkout.
- **PostToolUse/Edit,Write,MultiEdit**: convert an edited content file
  with this repo's own `pandoc_command` and run deckz's content checks
  (built-ins plus `templates/checks.py`'s) against it, reporting any
  problem back to the agent right away.
- **SessionStart**/**Stop**: snapshot the repo's fr/en content and lab
  notebook pairs when the session starts, and flag at `Stop` any pair
  changed on one language side only since then (same pairing as `deckz
  i18n stale`, but for the live session, not git history).

A repo can add its own Bash denials (e.g. never publish, never push to a
themed remote) from an optional `templates/hooks.py` module exposing:

```python
from collections.abc import Sequence
from pathlib import Path

from deckz.configuring.settings import GlobalSettings


def deny_bash(
    words: Sequence[str], cwd: Path, settings: GlobalSettings
) -> str | None:
    ...
```

called once per simple command of a Bash tool call, after deckz's own
built-in denials; returning a reason denies the call, `None` lets it
through (deckz's own reason wins if both would deny).

### Python hooks: contract and trust

`templates/jinja2/env.py`, `templates/assets_builders.py` and
`templates/checks.py` are plain
Python modules that `deckz` imports and runs: running `deckz` on a
repository executes its code with your permissions, like any build script,
so only use it on repositories you trust. Whatever they import is your
repository's own dependency, to install alongside `deckz`.

`deckz` checks each hook when loading it: the module must import cleanly
and define the expected function, `environment_for` must return a
`jinja2.Environment`, each object `assets_builders` returns must have
`build_assets` and `watched_dirs` methods, and `checks` must return a
`{str: callable}` mapping. A module may declare which
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

### HTML output

`deckz run --html` (off by default, on every `run` command) also produces
each deck as an HTML page, e.g. a reveal.js presentation: one per deck,
covering every part, like the full handout. `deckz` has no opinion on what
the page looks like: like a PDF, it's the repository's own main template,
`templates/jinja2/main.html` (`paths.jinja2_html_main_template`), rendered
with the same context as `main.typ`, fed with content files converted by
`html_pandoc_command` instead of `pandoc_command`. Since HTML has no
`#include`, the template inlines each converted fragment itself, with the
`fragment` function it's given:

```jinja
{% for part in parts %}
{% for item in part.sections %}
{% if item is string %}{{ fragment(item) }}{% else %}<h2>{{ item.title }}</h2>{% endif %}
{% endfor %}
{% endfor %}
```

The page is rendered in the deck's build directory, where every `assets`
subdirectory is linked, so it references assets relatively
(`img/logo.png`, `fonts/...`). `deckz` then packages it into
`html/<deck>-html/` (`html/en/...` for `--en`): the page as `index.html`,
plus every local file it references (`src`, `href`, `poster`, `data-src`,
`srcset`, ..., CSS `url()`/`@import`, recursively) and the
`html_static_dirs`, ready to serve or copy anywhere. A reference to a
missing file, a root-absolute one (`/img/...`) or one outside the build
directory fails the build; URLs (`https:`, `data:`, ...) and anchors are
left alone.

Filters can tell the two conversions apart with pandoc's `FORMAT` (e.g.
`typst` vs `revealjs`), so one Lua filter can handle a construct for both.

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
Logs and progress bars go to stderr, so stdout only carries a command's
results.

Exit codes: 0 on success, 1 on a deckz error (e.g. a missing flavor or a
failed compile), on `deckz check variables`/`deckz check content` findings,
on blocking `deckz i18n missing-en` gaps, or when a `deckz hooks`-installed
git hook refuses a commit, 2 on a command-line
usage error, 130 when interrupted with Ctrl-C (which stops the compilations
under way at once).

`deckz check variables`, `deckz search-sections` and `deckz i18n
missing-en` print one tab-separated finding per line; `deckz check content`
does too with `--plain`. With `--json`, `deckz check content` and the
above, as well as `deckz show tree`/`paths`/`settings`/`variables`, `deckz
deps` and `deckz asset deps`/`search`, print a single JSON document
instead (see each command's `--help` for its fields).

The main commands:

- `deckz run` (alias for `deckz run deck`, optionally restricted with
  `--parts`) / `deckz run file PATH` / `deckz run section SECTION FLAVOR` /
  `deckz run assets`: compile the deck in the current directory, a single
  content file, a specific section flavor, or the project's assets.
  Add `--en` to compile the English variant (see [Titles, variables and
  `--en`](#titles-variables-and---en)), `--html` to also produce the HTML
  deck (see [HTML output](#html-output)), or `--watch` to recompile on file
  changes instead of once. With `--dry-run`, every `deckz run` command
  except `run assets` only prints the outputs it would compile and, for
  each, the content fragments it would re-render (new or changed since
  that output's last build), without building anything.
  `run file`/`run section` write their output
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
  `variables_to_define` contract violation (`STRUCTURAL`). A shared flavor
  whose only failures are includes of deck-local files (one some deck's
  own `content/` has) is skipped: the decks using it cover it. Nothing is
  compiled.
- `deckz check` (alias for `deckz check content`): run deckz's generic
  content checks -- lab notebook IDs valid and unique (`lab-ids`), fr/en
  lab notebook pairs present and in sync (`lab-pairs`), hands-on notebooks
  with no stored outputs and demos with some (`lab-outputs`), asset credit
  lines (`title`/`author`/`license`, and their `_en`) free of LaTeX
  (`asset-credits`), no raw LaTeX in content (`raw-latex`), no hand-written
  link to the configured lab-publishing remote (`lab-urls`) -- plus, if
  `templates/checks.py` defines a `checks(settings)` function, the target
  repo's own, merged in under their own names (see
  `GlobalPaths.checks_module`). `--staged` checks the git index's staged
  version of every tracked file (exported to a scratch directory under
  `<git_dir>/.check/staged/`) instead of the working tree, so another
  session's unfinished edits neither block nor hide a check; a check
  needing the repository's git history or remotes does nothing under
  `--staged`. `--plain` for a script or an agent.
- `deckz check overflow [DECK_DIR]`: report a built handout's shrunk-to-fit
  frames (the `overflow_marker_label` Typst metadata marker, matching
  `formation.typ`'s `<formation-overflow>` by default), worst first, with
  the content file(s) building each one. Needs the handout already built
  (`deckz run --handout`, or a `deckz run file`/`deckz run section`
  preview); reads the PDF's text with poppler's `pdftotext`. Exits 1 if
  any frame was shrunk.
- `deckz check parity [DECK_DIR] [SLIDES...]` (extra: `deckz[parity]`,
  then `playwright install chromium`): compare a built deck's PDF and HTML
  slide by slide (`deckz run --handout --html`), reporting each pair's
  mean grayscale difference, the frames a reveal.js theme shrank to fit (a
  slide element carrying `dataset.ratio`/`dataset.overflow`), and anything
  the page logged, failed to load or tried to fetch from the network (a
  deck must work offline). By default writes an HTML report
  (`.build/parity/report.html`, sortable by gap, shrunk frames flagged),
  opened with `--open`; `--plain` instead prints a worst-first text report
  (agent-friendly) and writes contact sheets (PDF left, HTML right).
- `deckz hooks install`: install deckz's `pre-commit` (`deckz check
  --staged`) and `commit-msg` git hooks into the current repository.
  The `commit-msg` hook refuses a commit that changes one side of a fr/en
  content or lab notebook pair with no `Lang-sync` trailer (`fr-only
  (<reason>)`/`en-only (<reason>)`/`pending`, see `deckz i18n stale`
  above). Refuses to overwrite a hook file it didn't itself write, unless
  `--force` is passed. Also adds deckz's generic Claude Code hooks to
  `.claude/settings.json` (safe to call repeatedly; every other key of
  the file is left untouched) -- see [Claude Code
  hooks](#claude-code-hooks).
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
- `deckz i18n missing-en [--all] [--untranslated]`: report fr
  content/titles/variables with no English counterpart, i.e. what a `deckz
  run --en` would currently fail on (and, with `--untranslated`, titles
  that are a plain string).
- `deckz i18n stale [PATHS...]`: report content files and lab notebooks
  with changes not yet ported to their other-language sibling, computed
  from git history alone (a `Lang-sync` commit trailer, not a stored
  marker, exempts a one-sided change). `--plain` for a script or an agent.
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
- `deckz labs normalize NOTEBOOKS...`: normalize Jupyter notebooks (files,
  or directories searched recursively for `*.ipynb`) to their Colab
  conventions -- collapse every solution markdown heading cell by default
  (`labs.solution_heading`, "Solution" by default), and disable Colab's
  generative AI features. `--dry-run` lists what would change without
  writing.
- `deckz labs fmt [NOTEBOOKS...] [--check]`: rewrite every notebook
  (default: the configured notebooks directory) in deckz's canonical JSON
  style, so every notebook diffs the same way regardless of what last
  saved it. `--check` reports what would change without writing, and
  exits nonzero if anything would.
- `deckz labs ids [--dry-run]`: assign a published ID to every lab
  notebook that doesn't have one yet, refusing a duplicate.
- `deckz labs outputs EXECUTED NOTEBOOK [--max-image-kb KB] [--no-recompress]`:
  write an executed copy's cell outputs (and nothing else) back into a
  notebook, merging consecutive stream outputs and resolving carriage
  returns. A large `image/png` output (above `--max-image-kb`, default
  200) is re-encoded as JPEG when that's at least twice smaller (the
  common case for photos), or re-saved as an optimized PNG otherwise
  (charts and line art); `--no-recompress` disables this and needs no
  extra dependency, unlike the default, which needs Pillow
  (`deckz[labs]`) only when an image actually needs recompressing.
- `deckz labs check [--smoke] [--python INTERPRETER] [--timeout SECONDS]
  NOTEBOOKS...`: structural checks (uncollapsed/empty solution sections,
  stored error outputs) plus an execution of every code cell, in a
  throwaway directory, reporting which cells raise.
- `deckz labs compare [LAB_DIRS...]`: structural differences between
  fr/en notebook pairs beyond what a translation changes.
- `deckz labs missing`: every notebook present in only one language.
- `deckz labs dump NOTEBOOKS...`: a compact, readable view of one or more
  notebooks.
- `deckz labs publish [--break-published-links]`: replace the labs
  remote's branch with one commit of HEAD's lab notebooks, named by ID.

## Documentation

A partial code reference, generated from the docstrings, is published via
`mkdocs` (see `mkdocs.yml` and the `docs` directory).
