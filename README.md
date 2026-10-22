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
chromium`); `deckz labs gpu` needs the `vastai` CLI (`pip install
"deckz[gpu]"`, then `vastai set api-key`); `deckz videos render` needs
Manim and `ffmpeg`
(`pip install "deckz[videos]"`; `ffmpeg` itself isn't pip-installable,
install it with your system's package manager).

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
│       ├── course-notes.typ
│       └── env.py
├── content
│   └── some-section
│       ├── some-section.yml
│       ├── intro.md
│       └── advanced.md
├── course-notes
│   └── some-section
│       ├── intro.md
│       └── en
│           └── intro.md
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
- `templates/jinja2/course-notes.typ` and `course-notes`: optional, decks'
  course notes, written-out chapters of the content files -- see [Course
  notes](#course-notes).
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
typst_memory_max: 5GiB
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
- `typst_machine_compilations`: how many Typst compilations may run at
  once on the machine, across every deckz process of the user (unset by
  default: no such limit). `typst_parallel_compilations` only bounds one
  process, so two builds (two checkouts or worktrees, a `--watch` next to
  an agent's build) each believe they own the machine. Each compilation
  holds one of these slots while it runs (`flock`ed files in
  `$XDG_RUNTIME_DIR/deckz/`, freed by the kernel if a process dies), and
  waits for one, saying so, while they're all taken. Machine-specific, so
  the user's own `deckz.yml` is the natural place for it.
- `typst_memory_max`: stop a compilation whose process uses more memory
  than this (e.g. `5GiB`; unset by default: no limit). Its PDF then fails
  with a message naming the limit, instead of the machine running out of
  memory, which is what a `deckz run decks` over a repository with large
  decks needs. Checked every half second, on Linux only.
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
- `table_marker_label`: the Typst metadata label (default
  `formation-table`) `deckz check overflow --tables` queries for tables
  (`page`, `wrap`: the table's height over its height with no cell
  wrapped, as a percentage, and `overflow`: whether its longest words
  alone are wider than the frame) -- the table layout stays your theme's.
- `line_marker_label`: the Typst metadata label (default `formation-line`)
  `deckz check overflow` queries for header or footer lines that wrap
  (`page`, `line`: which one, `text`, `ratio`: its width over its room,
  `fix`: what to shorten, optional `frame`: true when that's in the page's
  frame, whose `# Title` line deckz then names) -- measuring them stays
  your theme's.
- `file_extensions`: the extensions tried, in order, when resolving a file
  include. Defaults to `[".md"]`. A `CLAUDE.md` or `AGENTS.md` is never a
  content file, wherever it is: a content or course notes directory can hold
  notes for the coding agents working in it.
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
  - `link_snippet`: how a content file links a lab, printed by `deckz
    labs new` with `{lab}` and `{kind}` filled in (default none).
  - `not_secrets`: values the `lab-secrets` check (and `deckz labs
    publish`, which refuses a notebook holding a credential) would take for
    one but aren't, e.g. a public dataset's read-only key.
  - `gpu`: the machines `deckz labs gpu` rents: `image` (default Colab's
    runtime image), `gpus` (names in order of preference, default
    `[Tesla_T4, RTX_A4000]`), `offer_filter` (a Vast.ai offer query),
    `disk_gb`, `boot_minutes`, `cpus` (each notebook's CPUs, default 2 as
    on Colab's T4 runtime), `ssh_key` (the private key whose public key
    Vast.ai has, default `~/.ssh/id_ed25519`), `fresh_dirs` (directories
    `up` snapshots and the queue restores before each notebook, so each
    one starts from the image's state as on a fresh Colab VM, default
    `[/usr/local]`, where pip installs), `metadata_key` (where a
    notebook's own metadata says what its runs need, default
    `shuuchuu.gpu`) and `hooks` (shell commands by name, run from the
    repository's root before and after the run of a notebook naming one).

    What a notebook's runs need, in its metadata:

    ```json
    "shuuchuu": {
      "gpu": {
        "variables": {"username": "DAGSHUB_USERNAME"},
        "secrets": {"token": "DAGSHUB_TOKEN"},
        "hook": "reset-server"
      }
    }
    ```

    `variables` and `secrets` map a variable the notebook assigns `""` on
    a line of its own to the environment variable (or `.env` entry) whose
    value `deckz labs gpu queue` puts there, in the copy it sends only; a
    secret's value is then redacted from every file kept locally, and
    `deckz labs outputs` stores no output that showed it. `hook` runs
    before the notebook is sent and once its run is done; notebooks naming
    the same hook run one at a time, even on different machines.
  - `outputs.hooks`: commands, by name, that `deckz labs outputs` (and
    `deckz labs gpu pass --write-outputs`) runs on a notebook once it wrote
    its outputs back, in order, for what only the repository knows to do to
    them, e.g. load a library's JavaScript from a CDN instead of embedding
    it in every report:

    ```yaml
    labs:
      outputs:
        hooks:
          evidently-cdn:
            run: [uv, run, python, tools/evidently_cdn.py]
            notebooks: ['mlops/**/demo-*.ipynb']
    ```

    `run` runs from the repository's root, with no shell, given the
    notebook's path (relative to the root) as its last argument, and edits
    the notebook in place; deckz then writes it back in its canonical style.
    `notebooks` (glob patterns relative to `paths.labs_notebooks_dir`, `**`
    for any directories; unset, every notebook) limits the hook to the
    notebooks it applies to. A hook that fails stops the command, naming
    its fix; the outputs stay written.

  The notebooks directory itself (default `{git_dir}/labs/notebooks`) is
  `paths.labs_notebooks_dir`, set like any other path under `paths:`.
  `deckz labs publish` also publishes the files committed under
  `paths.labs_published_dir` (default `{git_dir}/labs/published`), at the
  same paths: next to the notebooks, or, when `labs.published_files_remote`
  is set, as a commit of their own that replaces that remote's
  `labs.published_files_branch` (default `main`). That's how a repository
  with only a README and a `.devcontainer/` gets a GitHub Codespace for the
  notebooks without holding them; `deckz labs check --container` runs
  notebooks in that dev container, in that repository's workspace.
- `videos`: settings for the `deckz videos` commands, e.g.:

  ```yaml
  videos:
    publish_remote: videos
    publish_branch: main
    published_quality: h
    max_publish_size_mb: 100
    warn_publish_size_mb: 50
  ```

  - `publish_remote` / `publish_branch`: the git remote and branch
    `deckz videos publish` force-pushes the published renders to (default
    `videos`/`main`).
  - `published_quality`: the Manim quality flag (`l` to `k`) a render must
    be at to publish, and `deckz videos render`'s default `--quality`
    (default `h`).
  - `max_publish_size_mb` / `warn_publish_size_mb`: refuse, or just warn
    about, publishing a render over this size in MB (defaults `100`/`50`,
    GitHub's own limits).

  The scenes and videos directories (default `{git_dir}/figures/scenes`
  and `{assets_dir}/videos`) are `paths.scenes_dir`/`paths.videos_dir`,
  set like any other path under `paths:`.
- `setup`: what `deckz setup` checks and runs for a fresh clone, on top
  of deckz's own needs (git, pandoc):

  ```yaml
  setup:
    requires:
      - command: pdftocairo
        why: the SVG versions of the PDF figures, for HTML decks
        install: apt install poppler-utils
    steps:
      - name: reveal.js for HTML decks
        run: [npm, ci]
        creates: node_modules
  ```

  - `requires`: executables that must be on the `PATH`, each with what
    needs it (`why`) and how to install it (`install`), both shown when
    it's missing.
  - `steps`: commands run from the git root, without a shell, in order.
    A step whose `creates` path exists is done and skipped (`deckz setup
    --force` runs it anyway); one without `creates` runs every time.
- `worktree`: what `deckz worktree add` copies into a new worktree, on
  top of the checkout:

  ```yaml
  worktree:
    seed: [assets/typ, assets/svg, assets/web/vendor, assets/videos]
    required_for_agents: true
  ```

  `seed`: paths whose ignored files (the builds a fresh checkout lacks)
  are copied from the main checkout, file times kept, so that content
  stamps decide what to rebuild (see [Assets builders](#assets-builders)).
  Nothing is shared by a link: each worktree gets its own environment
  from `setup.steps` (e.g. `uv sync`, a second from uv's cache), and
  what every checkout shares goes in the user's `.env` (see
  [Usage](#usage)). `required_for_agents` (default false): a Claude Code
  session changes nothing in the main checkout, only in a worktree of
  its own (see [Claude Code hooks](#claude-code-hooks)).

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
`--lang`](#titles-variables-and---lang)).

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

Two flavors that differ by a few frames give each variant its own file,
listed only by the flavor that shows it, and list the files they share in
both: the section's `.yml` then says exactly what each flavor shows. A
flavor has no variables of its own: every file of a deck renders with the
same `variables.yml` values.

### Titles, variables and `--lang`

There is only ever one `deck.yml`/section `.yml` -- English is never a
separate deck or a duplicated section, only a `--lang en` option on `deckz
run`. `--lang fr en` (or `--lang fr --lang en`) handles both languages in
one pass, and so do `deckz check variables`, `deckz check overflow` and
`deckz search-sections`, which tag each finding with its language. `deckz
show`/`show paths`/`show variables` and `deckz section-files` show a single
resolved view, so they take a single `--lang en` to inspect the English
variant. Commands that act on the whole repository -- `deckz clean
content`, `deckz asset search`, `deckz asset deps` -- always cover both
languages, so an `en/` file counts as used whenever a `deckz run --lang en`
would pick it:

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
- English never silently falls back to French for a `{fr: ..., en: ...}` map
  that's missing its `en` key, or for a resolved file with no `en/` sibling:
  both fail the build immediately, so a translation that was started but
  left incomplete can't accidentally ship untranslated. A plain string, on
  the other hand, is never a gap -- it means "the same in every language" by
  design. `deckz i18n missing-en` audits a deck for the blocking gaps
  (and, with `--untranslated`, the merely informational plain strings)
  without needing to actually compile it.
- fr and en builds write to separate output paths (an `en/` subdirectory
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

`build_assets` runs before every build, so it should only rebuild what
changed. Don't decide that from file times: a git checkout gives every file
it writes the current time, so after a clone or a branch switch, sources look
newer than their outputs (and committed outputs older than their sources).
`deckz.stamps` decides from contents instead: `digest` the inputs, rebuild
unless `is_fresh(output, stamp, inputs)`, then `write_stamp(output, stamp)`,
which writes `<output>.stamp`. Commit the stamps of committed outputs, so a
fresh clone rebuilds none of them. `python_sources` lists a Python module and
the repo's modules it imports, the inputs of an output a module builds.
Digest the very bytes you build from, read before building: a source edited
in between then leaves a stamp it no longer matches, and the next build redoes
the output, where a digest taken after building would stamp a stale output as
up to date. `write_stamp` writes atomically, and so does
`deckz.utils.write_atomic(path, data)`: a deck compiling meanwhile never reads
a truncated output.

Builders run one checkout's assets build at a time: every command building
assets (`run`, `run section`, `run assets`, `--watch`...) holds a lock
(`.run/assets.lock`) while they run, and says so when it waits for another
one.

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


def checks(settings: GlobalSettings) -> Mapping[str, Callable[..., list[str]]]:
    ...
```

called once, with the repository's settings, to obtain every extra check
to run, each a callable returning its problems (empty if none) the same
way deckz's built-in checks do. A name colliding with a built-in check's
is rejected. A check may take a `paths` keyword argument, as the built-in
ones do: the Claude Code hooks pass the files they check (absolute
paths), and the check reports only about those, returning at once when
none is of a kind it reads; `deckz check` passes none, for the whole
repository. A check without the parameter always checks everything,
which makes the hooks wait for it.

Checks too slow, networked or not yet passing to run on every commit can
be listed in `deckz.yml`, by name, under `checks.opt_in`: `deckz check`
(hence the pre-commit hook) and the post-edit Claude Code hook skip them,
and `deckz check <name>` still runs them:

```yaml
checks:
  opt_in: [lab-outputs, published-videos]
```

A check is either blocking or deferred. A blocking check's problems fail
`deckz check`, hence the pre-commit hook and CI; a deferred one's are
printed (and listed by `deckz status`) without failing, unless the check is
named: their harm comes later than the commit, when a lab is published or a
deck uploaded or taught, so a contributor commits freely and the debt is
settled before then. By default every built-in check is deferred but
`lab-secrets` (a secret stays in the history), `jinja-syntax` and
`deck-definitions` (every `git pull` would break everyone's builds), and
every plugin check blocks. `checks.deferred` replaces deckz's list, naming
built-in and plugin checks alike (`[]` makes every check block):

```yaml
checks:
  deferred: [lab-ids, lab-pairs, lab-format, asset-credits, raw-latex, lab-frames]
```

### Claude Code hooks

`deckz hooks install` also adds deckz's own Claude Code hooks to
`.claude/settings.json` (Claude Code is treated as a requirement of a
deckz-managed repository, like git): `deckz hooks pre-bash`/`post-bash`/
`pre-edit`/`post-edit`/`session-start`/`stop`/`worktree-create`/
`worktree-remove`, backed by `deckz.agent_hooks` and
`deckz.agent_checkouts`. The generic rules they enforce need no
repo-specific knowledge:

- **PreToolUse/Bash**: deny staging everything (`git add -A`/`.`/`-u`),
  `git commit -a`, `git clean` without `--dry-run`, and anything that
  would discard uncommitted changes (`git checkout`/`restore` on a
  changed file, `git reset --hard`, a bare `git stash`) -- several Claude
  Code sessions may share one checkout. Also deny skipping the git hooks
  (`--no-verify`, `git commit -n`, `git -c core.hooksPath=...`): they run
  the repository's checks.
- **PostToolUse/Edit,Write,MultiEdit,NotebookEdit**: record the edited
  file; convert a content file with this repo's own `pandoc_command` and
  run deckz's content checks (built-ins plus `templates/checks.py`'s) on
  it alone, reporting any problem back to the agent right away (about a
  second: a check taking `paths` reads only that file).
- **Stop**: flag a fr/en content or lab notebook pair changed on one
  language side only (same pairing as `deckz i18n stale`), and run the
  PostToolUse checks on every changed content file they haven't passed
  as it is now: one a shell command wrote, which no PostToolUse hook
  sees. In a linked worktree, what changed is the worktree's own work:
  `git status`, and the commits on its branch that the main checkout's
  branch doesn't have. Elsewhere, it is the files the session's edit
  tools changed: never another session's work. A one-sided pair is
  reported once per session, at most ten paths per list.
- **WorktreeCreate**/**WorktreeRemove**: the worktrees Claude Code makes
  (`claude --worktree <name>`, EnterWorktree with a name, a subagent's
  worktree isolation) are `deckz worktree add`'s, `../<repo>--<name>`
  with the builds copied and `deckz setup` run, and are removed by
  `deckz worktree remove`, which keeps one holding work nothing else has.
- With `worktree.required_for_agents`, the main checkout is the user's:
  agents change files only in a worktree of their own.
  **PreToolUse/Edit,Write,MultiEdit,NotebookEdit** denies an edit of one
  of its files (or of a worktree's from a session still in the main
  checkout). **PreToolUse/Bash** refuses there what is clearly a change:
  git and deckz commands other than read-only ones (`git merge
  --ff-only`, `git worktree` and `deckz worktree` are allowed), a
  redirection into it, `cp`/`mv`/`rm`/`sed -i`/`find -delete`… writing
  one of its files, `uv sync`/`pip`/`npm install`. Anything else runs (a
  script, a report written to `/tmp`), after a snapshot of the main
  checkout's `git status`; **PostToolUse/Bash** compares, and reports
  what the command changed there, which the session may then put back
  (`git restore`, `rm`) and only that. A shell test skips that hook's
  start-up when no snapshot is pending, i.e. in a worktree.
  **SessionStart** tells a session starting in the main checkout to
  create its worktree, and `deckz worktree land` puts a worktree's
  commits on the main checkout's branch. These are guard rails against an
  agent's mistakes, not a sandbox: a change git ignores (a virtual
  environment, a build) or outside the repository isn't seen.

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
`html/<deck>-html/` (`html/en/...` for `--lang en`): the page as `index.html`,
plus every local file it references (`src`, `href`, `poster`, `data-src`,
`srcset`, ..., CSS `url()`/`@import`, recursively) and the
`html_static_dirs`, ready to serve or copy anywhere. A reference to a
missing file, a root-absolute one (`/img/...`) or one outside the build
directory fails the build; URLs (`https:`, `data:`, ...) and anchors are
left alone.

Filters can tell the two conversions apart with pandoc's `FORMAT` (e.g.
`typst` vs `revealjs`), so one Lua filter can handle a construct for both.

### Course notes

A deck's course notes are its written-out reference, read during and after a
training: a document rather than slides, which explains what the slides only
outline. They are made of chapters, one per content file: the chapter of
`content/<path>.md` is `course-notes/<path>.md` (`paths.course_notes_dir`),
its English version `course-notes/<dir>/en/<name>.md`, in the same Markdown as
the slides. A chapter is shared like the content file it writes out: every
deck including that file gets it.

`deckz run course-notes` (from a deck's directory, `--lang`, `--watch` and
`--dry-run` as for `deckz run`) compiles the deck's course notes: its parts
and sections, each content file replaced by its chapter -- once, where the
first file it covers comes --, without the files that have none (it lists
them), rendered and converted like the deck's own files, through the
repository's own main template, `templates/jinja2/course-notes.typ`
(`paths.jinja2_course_notes_main_template`, same context as `main.typ`). The
PDF is `pdf/course-notes/<deck>-course-notes.pdf` (`paths.course_notes_pdf_dir`;
`pdf/course-notes/en/` in English), which `--sync` and `deckz upload` leave
alone. `deckz show course-notes` lists each content file of the deck with its
chapter: `written`, `covered`, `skipped` or `missing`.

`deckz run --course-notes` builds them along with the slides, in one command
(`--watch` then also watches the chapters), and `deckz run decks --course-notes`
those of every deck with chapters; the course notes are always whole, whatever
`--parts`, and a language with no chapter is left out instead of failing.
With `--no-handout --no-presentation --no-print`, only the course notes are
built. `DECKZ_RUN_COURSE_NOTES=true` makes it the default.

`deckz.yml`'s `course_notes` settings:

```yaml
course_notes:
  # Content files with no chapter on purpose, as patterns on their paths
  # relative to content/, without extension (`PurePosixPath.full_match`).
  skip: ["about/**", "**/quiz*"]
  # A content file another one's chapter covers (a short variant).
  same_as:
    some-section/intro-short: some-section/intro
  # The PDF's name: <deck>-<suffix>.pdf.
  suffix: course-notes
```

Chapters are fr/en pairs like content files: `deckz i18n stale`, the
`commit-msg` hook's `Lang-sync` trailer and the Claude Code hooks follow
them. `deckz check` checks that each chapter is named after a content file
(`course-notes-files`, which also checks `same_as`) and exists in both
languages (`course-notes-pairs`).

### Upgrading from 31.x (`clean content`)

`deckz clean content` is gone: it deleted every content file no deck
included, including the ones a repository keeps on purpose for decks to
come. `deckz deps` now lists those files (and `deckz deps --json` has them
under `"unused_files"`), and you delete the ones you choose.

### Upgrading from 30.x (`--lang`)

`--en` is gone: use `--lang en` instead, or `--lang fr en` to handle both
languages in one pass where a command accepts several (see [Titles,
variables and `--lang`](#titles-variables-and---lang)). The text and JSON
outputs of `deckz check variables`, `deckz check overflow` and `deckz
search-sections` now carry each finding's language (a `<lang>` column, or
a `"lang"` field).

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

Option defaults can come from the environment, from the closest `.env`
file above the current directory, or from the `.env` in the user's config
directory (e.g. `~/.config/deckz/.env`, next to the user's `deckz.yml`),
which every checkout of every repository reads: the place for one's own
defaults and credentials. The environment wins over the checkout's
`.env`, which wins over the user's, and an option given on the command
line wins over all of them:

- `DECKZ_LANG`: the languages `deckz run`, `deckz check variables`, `deckz
  check overflow` and `deckz search-sections` process when `--lang` isn't
  given, space-separated, e.g. `DECKZ_LANG="fr en"`.
- `DECKZ_RUN_<OPTION>`: any option of every `deckz run` command, e.g.
  `DECKZ_RUN_PRINT=false` or `DECKZ_RUN_OPEN=false`. The same variable
  applies to every `run` subcommand, whose own defaults differ (`run
  decks`/`shared`/`all` only build presentations): set `HANDOUT`,
  `PRESENTATION` and `PRINT` together to get the same outputs from all of
  them.

`deckz <command> --help` lists the variables each option reads. For
instance, a `.env` (typically git-ignored) building only each deck's whole
handout, in both languages, by default:

```sh
DECKZ_LANG="fr en"
DECKZ_RUN_HANDOUT=true
DECKZ_RUN_PART_HANDOUTS=false
DECKZ_RUN_PRESENTATION=false
DECKZ_RUN_PRINT=false
```

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

- `deckz status`: where your work stands, and what's left before
  committing, teaching or publishing. Your changes are the working tree's
  plus the commits not on the upstream branch yet (`--since REV` to count
  from elsewhere). It lists the content checks' problems (`--no-checks`
  skips them), what your changes leave to translate (the English gaps of
  the decks they reach included, as `deckz i18n missing-en` finds them)
  and the repository's backlog, lab notebooks and videos not published as
  committed or rendered (compared with their remotes as last fetched;
  `--fetch` fetches them first), the demos you changed whose code changed
  since their outputs (`deckz labs stale`, the others counted), and the
  built PDFs of the decks your changes reach that don't match them
  (`--no-decks` skips them). Each item says how to resolve it; `--json`
  for scripts, each section with a stable `key`. `deckz status DECK`
  reports on one deck instead, whoever made its changes: the checks'
  problems in its files (deferred ones included), its English gaps, its
  files waiting for a port, and its built PDFs not matching its content,
  with their shrunk frames and wrapping lines. `deckz show affected
  [PATH...] [--since REV]` prints the decks a change to PATHs, or the
  changes since REV, reach.
- `deckz new deck DIR --name NAME --title TITLE`, `deckz new section
  PATH [--title TITLE]`, `deckz labs new LAB hands-on|demo`: create the
  files of a new deck, shared section (its `.yml` with a `full` flavor, a
  first file and its `en/` twin; existing sections sharing a word with it
  are listed first) or lab notebook pair (same cells in both languages,
  in deckz's format, with their IDs), refusing to overwrite anything. A
  repository's own starting files go under `templates/scaffold/`:
  `deck/` (every file, rendered with Jinja's `{{ name }}`/`{{ title }}`,
  minus a `.jinja` suffix: name the template's `deck.yml.jinja`, or deckz
  takes it for a deck)
  and `lab/hands-on.ipynb`/`lab/demo.ipynb`. `labs.link_snippet` (e.g.
  `'{{ "{lab}" | lab("{kind}") }}'`) is printed after `labs new`, filled
  in, for the content file linking the lab.
- `deckz setup`: set up a clone, and run it again after pulling. It
  fetches the deckz checkout it runs from (an editable install) and
  reports it when it's behind its upstream branch, with the `git pull`
  to run; checks the executables deckz and the repository need (`setup.requires`
  above), saying how to install a missing one; installs the git hooks;
  runs the repository's `setup.steps` not done yet; and reports the
  videos never rendered (`--videos` renders them). `--check` only
  reports, `--claude` also installs the Claude Code hooks. It exits 1
  while something is missing or failed, and is safe to run any number of
  times.
- `deckz worktree add NAME [--base REV]`: create a second checkout of the
  repository, `../<repo>--NAME`, on a new branch `ws/NAME` (from the main
  checkout's `HEAD` unless `--base`), to work on something without
  disturbing the main checkout's builds and uncommitted edits. It copies
  the builds `worktree.seed` lists (see above), then runs `deckz setup`
  there. `deckz worktree list [--json]`
  lists the worktrees with their uncommitted changes and their commits no
  other branch has; `deckz worktree land [NAME]` rebases a worktree's
  branch (by default, the one the command runs in) onto the main
  checkout's and fast-forwards the main checkout to it; `deckz worktree
  remove NAME` removes one, and its branch, refusing while it holds
  either (`--force` loses the uncommitted changes and keeps the branch).
- `deckz run` (alias for `deckz run deck`, optionally restricted with
  `--parts`) / `deckz run file PATH` / `deckz run section SECTION FLAVOR` /
  `deckz run assets`: compile the deck in the current directory, a single
  content file, a specific section flavor, or the project's assets.
  Add `--lang en` to compile the English variant, or `--lang fr en` for
  both (see [Titles, variables and `--lang`](#titles-variables-and---lang)),
  `--course-notes` (on `run` and `run decks`) to also compile the course
  notes (see [Course notes](#course-notes)),
  `--html` to also produce the HTML
  deck (see [HTML output](#html-output)), or `--watch` to recompile on file
  changes instead of once. With `--dry-run`, every `deckz run` command
  except `run assets` only prints the outputs it would compile and, for
  each, the content fragments it would re-render (new or changed since
  that output's last build), without building anything.
  A deck's handout comes whole and, unless `--no-part-handouts`, one per
  part; its presentations come one per part only. `--parts` restricts
  every output to the parts listed, the whole deck's handout included.
  `--sync` (the default; `--no-sync` turns it off) removes the PDFs no
  build of the deck produces anymore, once everything compiled: a removed
  or renamed part's, a renamed deck's, a stray file. It only looks at the
  languages the run built, and keeps what the run merely skipped (part
  handouts after `--no-part-handouts`, presentations after
  `--no-presentation`, other parts' PDFs under `--parts`). A failed build
  removes nothing, nor does a run producing no PDF at all; `--dry-run`
  lists what would go.
  `run file`/`run section` take their path relative to `content/`
  (`nn/intro`, `nn/ae`), or as found from the current directory or the
  repository's root (`content/nn/intro.md`, as editors and `git status`
  show it). They write their output
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
  of its files. English is strict: the first gap in translation coverage
  aborts the run, before anything is compiled. `run shared`/`run all` write their throwaway output
  under `<git_dir>/.run/`. `run decks --since REV` compiles only the decks
  the changes since REV (the working tree's included) reach, as `deckz
  show affected --since REV` lists them: before pushing, or nightly in CI.
  `run decks --report FILE` builds every deck whatever fails, then writes
  the failures to FILE in Markdown, each with the `deckz run` command
  reproducing it and its errors, for a person or an agent to fix.
- `deckz check variables`: statically survey every shared section's every
  named flavor (not just the ones some deck currently uses), with the
  repository-wide `variables.yml`, plus every real deck, with its own
  `variables.yml` files, as a real build would. Reports a fragment reading a
  `variables.xxx`/`variables['xxx']` name nothing sets (`UNDEFINED`), a
  fragment that fails to parse (`UNPARSABLE`), and a flavor/deck that fails
  to parse at all (`STRUCTURAL`). A shared flavor
  whose only failures are includes of deck-local files (one some deck's
  own `content/` has) is skipped: the decks using it cover it. Nothing is
  compiled.
- `deckz check` (alias for `deckz check content`): run deckz's generic
  content checks -- lab notebook IDs valid and unique (`lab-ids`), fr/en
  lab notebook pairs present and in sync (`lab-pairs`), hands-on notebooks
  with no stored outputs and demos with code with some, shown by Colab (no
  `private_outputs`), and no demo cell whose outputs are only whitespace
  (`lab-outputs`), nothing that looks like a credential
  in a notebook's cells or stored text outputs (`lab-secrets`; the labs
  are public), notebooks in deckz's canonical JSON (`lab-format`, fixed by
  `deckz labs fmt`),
  asset credit lines (`title`/`author`/`license`, and their `_en`) free of LaTeX
  (`asset-credits`), no raw LaTeX in content (`raw-latex`), every content
  file's Jinja parsing with `templates/jinja2/env.py`'s environment, its filters
  and tests known to it (`jinja-syntax`: a broken tag otherwise fails only the
  build), no hand-written
  link to the configured lab-publishing remote (`lab-urls`), course notes
  chapters named after a content file and in both languages
  (`course-notes-files`, `course-notes-pairs`, see [Course
  notes](#course-notes)) -- plus, if
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
  the content file and line of each one's `# Title`. Needs the handout
  already built (`deckz run --handout`, or a `deckz run file`/`deckz run
  section` preview), and reads what its compilation recorded (a build by
  an older deckz is queried again and matched by title with the PDF's
  text, from poppler's `pdftotext`). Then the header and footer lines that
  wrap onto a second line (the `line_marker_label` marker, `<formation-line>`
  by default: a long section title in the breadcrumb, a long frame title,
  a long deck title in the footer), each with its text, its pages and what
  to shorten (a frame title with its `# Title`'s file and line); a
  handout built by an older deckz, which didn't record them, gets a note
  to build it again. Exits 1 if any frame was shrunk or any line wraps.
  `--json` tags each finding with its `kind` (`frame` or `line`, `table`
  with `--tables`). `--lang en` checks the English build (`deckz run
  --lang en`, kept under `en/` in the build and PDF directories), `--lang
  fr en` both, each frame tagged with its language. `--tables`
  reports the tables instead (the
  `table_marker_label` marker), most wrapped first, flagging those whose
  longest words alone are wider than the frame; exits 1 if any is.
- `deckz check parity [DECK_DIR] [SLIDES...] [--lang LANG...]` (extra:
  `deckz[parity]`, then `playwright install chromium`): compare a built
  deck's PDF and HTML slide by slide (`deckz run --handout --html`),
  reporting each pair's mean grayscale difference, the frames a reveal.js
  theme shrank to fit (a slide element carrying
  `dataset.ratio`/`dataset.overflow`), and anything the page logged, failed
  to load or tried to fetch from the network (a deck must work offline).
  French builds by default (or `DECKZ_LANG`'s), `--lang en` the English ones
  (under `en/`), `--lang fr en` both, one after the other. By default
  writes an HTML report per language (`.build/parity/report.html`,
  `.build/en/parity/report.html`, sortable by gap, shrunk frames flagged),
  opened with `--open`, and prints a summary whose lines start with their
  language; `--plain` instead prints a worst-first text report per
  language (agent-friendly) and writes contact sheets (PDF left, HTML
  right); `--json` prints an array, one object per language with its
  `"lang"`.
- `deckz hooks install`: install deckz's `pre-commit` (`deckz check
  --staged`) and `commit-msg` git hooks into the current repository's
  hooks directory (git's `core.hooksPath` when set, so a repo can commit
  them, else `.git/hooks/`). Each hook, like each Claude Code hook
  command, runs `deckz` from the `PATH`, else `uv run --quiet deckz`.
  The `commit-msg` hook marks a commit that changes one side of a fr/en
  content or lab notebook pair with no `Lang-sync` trailer `Lang-sync:
  pending` (or keeps the author's `fr-only (<reason>)`/`en-only
  (<reason>)`, see `deckz i18n stale` above), and refuses one whose
  `Lang-sync` line isn't read (misspelled, or not in the last paragraph). Refuses to overwrite a hook file it didn't itself write, unless
  `--force` is passed. Also adds deckz's generic Claude Code hooks to
  `.claude/settings.json` (safe to call repeatedly; every other key of
  the file is left untouched) -- see [Claude Code
  hooks](#claude-code-hooks). With `--ci`, also writes
  `.github/workflows/deckz.yml`, a GitHub Actions workflow giving every
  contributor's commits the hooks' checks, installed or not: `deckz check`
  and `deckz hooks check-commits` (the pushed or proposed commits'
  `Lang-sync` lines, which must be read) on every push and pull request,
  `deckz.yml`'s `ci.nightly_checks` every night, and, on Sundays (or every
  night), the handouts of the decks the period's commits reach, in the
  `ci.builds` languages (`deckz run decks --since`, every deck when no
  commit is older than that). When those fail and `ci.report_to` names
  someone, `deckz hooks ci-report` opens an issue labeled `deckz-ci` (or
  comments on the open one) mentioning and assigning them, which GitHub
  emails them: each failure with the command reproducing it and its
  errors, written to be pasted to an agent. Its `ci` settings:
  `deckz_repository` and `deckz_ref` (a deckz checked out next to the
  repository, for one installing it from `../deckz`), `apt_packages`
  (system packages its dependencies, or its assets builders, need),
  `nightly_checks`, `builds` (e.g. `[fr, en]`; none by default, no build),
  `builds_schedule` (`weekly`, the default, on Sundays at 04:00 UTC, or
  `nightly`), `videos_repository` (the `owner/name` the videos are
  published to, whose renders the builds fetch first: `deckz videos
  fetch`), `user_variables` (written as the CI machine's own
  `variables.yml`: what each person's own file sets, such as a trainer's
  name, with stand-in values), `report_to` (GitHub logins) and
  `cache_paths` (directories of generated files, such as the assets
  builders' outputs, kept from one build to the next with
  `actions/cache`, so only the stale ones are rebuilt; never one holding
  committed files, which a restore would overwrite).
- `deckz hooks ci-report REPORTS [--dry-run]`: the scheduled workflow's
  last step, when its checks or builds fail: REPORTS holds their outputs
  (`checks.txt`, `builds.md`), turned into the `deckz-ci` issue described
  above, with the job's `GITHUB_TOKEN`. `--dry-run` prints the body.
- `deckz show` (alias for `deckz show tree`): show the resolved tree of
  sections and files for the current deck.
- `deckz show settings` / `deckz show variables` / `deckz show paths`:
  print the resolved settings/variables/file paths for the current
  directory.
- `deckz run course-notes` / `deckz show course-notes`: compile the current
  deck's course notes / list its content files with their chapters (see
  [Course notes](#course-notes)).
- `deckz show frames [PDF] [--lang] [--json]`: each page of a built deck
  PDF (default: the deck's whole handout; also a `run file`/`run section`
  preview's, under `.run/`) with the content file and line
  of its frame's `# Title`, and its title; title, outline and divider
  pages aren't listed. A deck build adds an invisible `<deckz-frame>`
  Typst marker after each frame heading for it (on the converted copy,
  never the content file), and each compilation records where they landed
  next to its PDF (`<pdf>.markers.json` in the build directory, with the
  theme's shrunk-frame and table markers), which this reads at once (it
  queries the build, a whole compilation, after a build by an older
  deckz): it builds nothing itself.
- `deckz deps [SECTION] [FLAVOR]`: show shared sections/flavors usage
  across the repository, including unused ones, and the content files no
  deck includes (shared or local, fr or `en/`), with their number of
  frames. It only lists those files: unused content can be kept on
  purpose, as material for decks to come.
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
- `deckz clean` / `deckz clean all`: remove build directories. `deckz clean all` also
  removes the whole `<git_dir>/.run/` scratch tree (`run shared`/`run all`/
  `run file`/`run section`), and `<git_dir>/.check/` (`check variables`).
- `deckz i18n missing-en [--all] [--untranslated]`: report fr
  content/titles/variables with no English counterpart, i.e. what a `deckz
  run --lang en` would currently fail on (and, with `--untranslated`, titles
  that are a plain string).
- `deckz i18n stale [PATHS...]`: report content files and lab notebooks
  with changes not yet ported to their other-language sibling, computed
  from git history alone (a `Lang-sync` commit trailer, not a stored
  marker, exempts a one-sided change). `--plain` for a script or an agent.
  A file leaves it when a commit changes its sibling, or names either side
  in a `Lang-synced: <path>` trailer.
  A repository moving to trailers from markers of its own (or with
  one-sided commits it already settled) sets `i18n.synced_at` in
  `deckz.yml` to the commit up to which every pair is in sync: that commit
  and its ancestors are ignored.
- `deckz i18n mark-synced PATHS... --reason TEXT`: record that what
  `deckz i18n stale` lists for these files needs no port after all (a
  case fix committed without a `Lang-sync` trailer): an empty commit with
  the reason and a `Lang-synced: <path>` trailer per file. Nothing staged
  goes into it.
- `deckz generate-agent-notes`: print onboarding notes for an AI coding
  agent working in the repo (conventions not already covered by `--help`,
  e.g. the section/flavor syntax and local-override resolution). Prints to
  stdout, e.g. `deckz generate-agent-notes > CLAUDE.md`.
- `deckz generate-completion {bash,zsh,fish}`: print a shell completion
  script (see [Shell completion](#shell-completion)).
- `deckz upload`: upload built PDFs to Google Drive. It refuses, naming
  them, when a PDF doesn't match the deck's content anymore: a content
  fragment changed since it was built, the Markdown conversion changed, or
  no build produces it. Rebuild or delete those, or pass `--include-stale`.
  It refuses too while the content checks report a problem in the deck's
  files (deferred checks included: the upload is when they're due; a
  problem is the deck's when the file it starts with is under the deck's
  directory, one the deck resolves, or an asset its content shows, found
  by rendering it as `deckz asset search` does), unless `--skip-checks`.
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
  Then it runs the `labs.outputs.hooks` matching the notebook on it.
- `deckz labs stale [NOTEBOOKS...] [--plain] [--json]`: list the demos
  whose code cells changed after their outputs were written, computed
  from git history alone: the outputs were written by the last commit (or
  the working tree) changing them, and the code changed since (blank and
  comment-only lines aside). Exits 1 when it lists one. Each state's
  digests are cached by blob id in `.run/lab-outputs.json`, since a demo
  can weigh megabytes.
- `deckz labs mark-current NOTEBOOKS... --reason TEXT`: record that what
  `deckz labs stale` lists for these demos needs no rerun (a comment, a
  download line): an empty commit with the reason and a
  `Lab-outputs-current: <path>` trailer per demo, which a commit making
  such a change can also carry itself. Nothing staged goes into it.
- `deckz labs check [--smoke] [--python INTERPRETER] [--container]
  [--timeout SECONDS] NOTEBOOKS...`: structural checks (uncollapsed/empty
  solution sections, stored error outputs) plus an execution of every code
  cell, in a throwaway directory, reporting which cells raise; it exits
  with code 1 on any problem, a failed shell command included (but
  `nvidia-smi` on a CPU), and lists the notebooks that have one. `--smoke`
  caps every Lightning `Trainer` to one short epoch, a Lightning the
  notebook installs itself (`!pip install lightning`) included: it's capped
  when first imported. Shell
  commands other than data fetches are skipped (a lab may `pip install` or
  `git push`); `--container` runs everything, with a real kernel, in the
  published repository's dev container
  (`paths.labs_published_dir`/`.devcontainer/devcontainer.json`, built
  with Docker): what a Run all does in GitHub Codespaces, and in Colab for
  a notebook that needs no GPU. A prebuilt `image` is pulled, unless
  `customizations.deckz.dockerfile` names the Dockerfile it's built from:
  that one is then built locally under the image's name, so a change is
  checked before the image is published. The container is thrown away after each
  notebook, and nothing is mounted into it. When the kernel dies (a setup
  cell that kills it for Colab to restart it on what it installed), the
  notebook runs once more from the start, as a trainee would run it again.
  A failing shell command (`!cmd`, `%pip`) never raises, in Colab as here:
  the cell goes on, and the report gives it a line of its own,
  `[i] shell command exited with code N: cmd`, before "no code cell
  raised" (in a real kernel, a guard deckz starts it with wraps IPython's,
  ipykernel's and Colab's shell runners; `labs gpu report` reads the same
  lines from `<notebook>.shell`). A command expected to fail (`!nvidia-smi`
  on a CPU) shows there too.
- `deckz labs compare [LAB_DIRS...]`: structural differences between
  fr/en notebook pairs beyond what a translation changes.
- `deckz labs missing`: every notebook present in only one language.
- `deckz labs dump NOTEBOOKS...`: a compact, readable view of one or more
  notebooks.
- `deckz labs publish [--break-published-links] [--skip-checks]`: replace
  the labs remote's branch with one commit of HEAD's lab notebooks, named
  by ID, and publish the files committed under `paths.labs_published_dir`
  (with them, or to `labs.published_files_remote`). Refuses while the
  content checks report a problem in a notebook (deferred ones included),
  unless `--skip-checks`; a credential is refused regardless.
- `deckz labs gpu up|queue|run|status|fetch|report|down` (extra:
  `deckz[gpu]`): run notebooks on a rented GPU machine the way Colab runs
  them -- Colab's runtime image, `labs.gpu.cpus` CPUs per run, peak RAM
  recorded (Colab's T4 runtime has 12.7 GB). `up` rents the cheapest
  reliable offer (a machine that fails to boot is destroyed and avoided
  from then on); `queue [--short] NOTEBOOKS...` sends notebooks (`--short`
  sets their `SHORT_RUN = False` line to `True`; a notebook's metadata can
  ask for variables, secrets and a hook, see `labs.gpu` above; queueing a
  notebook again reruns it); `run` starts the queue, detached, each
  notebook saved after every cell, `labs.gpu.fresh_dirs` restored before
  each one;
  `status [--watch]` follows it, fetching, appending each finished run's
  report to `notes.md`, running the hooks of finished runs and sending
  the notebooks held for them, until done under `--watch`; `fetch` copies
  the executed notebooks; `report [--plain]` gives each one's exit code,
  run time, peak RAM, the cells that raised and the slowest ones; `down`
  destroys the machine, which bills until then. `--machine NAME` (default
  `main`) runs several machines at once; `status`, `report` and `down`
  without it act on every one. Each machine's state and files live in
  `.run/gpu/<name>/` (`paths.labs_gpu_dir`). Then `deckz labs outputs`
  writes a demo's outputs back.
- `deckz labs gpu pass NOTEBOOKS... [--short] [--max-hours] [--write-outputs]
  [--dry-run [--json]] [--gpu GPU...]`: all of the above in one command, which
  always destroys its machine: once the runs are done, when one fails, past
  `--max-hours` from the rental (default 4), and on Ctrl-C, SIGTERM or
  SIGHUP, whenever it comes (one arriving while it rents waits until the
  machine is recorded, and only the first one stops the pass: `timeout 60
  uv run deckz ...` sends two). It refuses a machine already rented
  (`--machine`), one another pass is running, and, before renting, a
  notebook it couldn't run. When nothing could be rented, it says why for
  each GPU (no offer matching `labs.gpu.offer_filter`, or each offer tried
  and what Vast.ai answered). `--gpu RTX_A4000 RTX_3090` (or `--gpu RTX_A4000
  --gpu RTX_3090`) names the GPUs to rent instead of `labs.gpu.gpus`, in order
  of preference; notebook paths written right after them are told apart.
  `--write-outputs` (off by default: it
  overwrites) writes each demo's outputs back when its full run exited 0
  with no cell raising (but those tagged `raises-exception`) and no shell
  command failing; such a run fails the pass.
  `--dry-run` rents nothing: the offer it would rent now, each notebook's
  last successful run time from the machines' `notes.md` (the main
  checkout's too, from a worktree), the estimated time and cost (ten
  minutes added for booting) and the ceiling's. `status --plain` gives each
  machine's GPU, price per hour and rental time; `status --offline` reads
  only what this checkout keeps of its machines (no call to Vast.ai, nothing
  fetched), for something polling often, like studioz's status bar.
- `deckz videos render [SCENE] [--quality] [--force]` (extra: `deckz[videos]`,
  Manim, plus `ffmpeg`): render every `@register_scene` class under
  `videos.scenes_dir` that's missing, stale, or at another quality than
  `--quality` (default `videos.published_quality`), in parallel. A render
  is stale when its scene's module, or a module under `scenes_dir`'s parent
  it imports, has changed since (a `.stamp` next to the render, see
  `deckz.stamps`). A scene
  is marked with `deckz.videos.register_scene` (optionally
  `languages=("fr", "en")` for one with on-screen text, rendered once per
  language). SCENE restricts to one video (its path, as `deckz videos
  list` prints it, or its class name); `--force` re-renders even what
  looks up to date (after editing a data file a scene reads, say).
- `deckz videos fetch [--source REMOTE_OR_URL]`: put the published
  renders in place of those this checkout never rendered (a CI job, a
  contributor without Manim), from `videos.publish_remote`'s
  `videos.publish_branch` or SOURCE, each with its poster frame (needs
  `ffmpeg`). A render already there is never replaced. A fetched render
  has no sources stamp and is dated to the epoch, so `deckz videos render`
  renders it again. A video never published is listed; exits 1 when a
  render got no poster.
- `deckz videos list`: list every registered scene's renders, one per
  line (quality stamp or `-`, path under `videos.videos_dir`, class name).
- `deckz videos publish [--break-published-links]`: replace the videos
  remote's branch with one commit of every scene's current renders,
  refusing one missing, stale, at the wrong quality, or over the publish
  size limit, or that would drop an already-published render's path.

## Documentation

Built with `mkdocs` (see `mkdocs.yml` and the `docs` directory): a guide for
the people running a deckz-managed repository, one page per task
(`docs/guide/`), and a partial code reference generated from the
docstrings.
