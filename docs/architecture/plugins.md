# The repository's plugins

deckz is generic. A managed repository brings its own theme, house rules and tools in
two ways: Python modules under `templates/` that deckz loads, and commands declared in
`deckz.yml` that deckz runs. This page is the boundary between them: what deckz calls,
and what a repository may import from deckz.

## Python plugins

Each plugin module is loaded by [`load_hook`][deckz.components.hooks.load_hook]. An
import failure, a missing function, or a `DECKZ_HOOKS_VERSION` other than deckz's
`HOOKS_VERSION` (1 when left out) is a [`HookError`][deckz.exceptions.HookError]. The
caller also checks what the function returns.

| Module | Function | Called by | For |
|---|---|---|---|
| `templates/jinja2/env.py` | `environment_for(suffix) -> jinja2.Environment` | [`Renderer`][deckz.components.renderer.Renderer] | The Jinja environment of each content file suffix: delimiters, filters, macros |
| `templates/assets_builders.py` | `assets_builders(assets_dir, compiler) -> Iterable[AssetsBuilderProtocol]` | [`AssetsBuilder`][deckz.components.assets_builder.AssetsBuilder] | Generated assets: plots, figures |
| `templates/checks.py` | `checks(settings) -> Mapping[str, Callable[..., list[str]]]` | [`ChecksRunner`][deckz.components.checks.ChecksRunner] | House-rule checks, blocking unless `checks.deferred` lists them |
| `templates/hooks.py` | `deny_bash(words, cwd, settings) -> str \| None` | [`agent_hooks`][deckz.agent_hooks] | Further Bash commands an agent may not run |

Loading a plugin runs arbitrary code from the repository, with the user's permissions.
This is a trust boundary: deckz runs only on repositories one trusts, like any build
script.

## Commands declared in `deckz.yml`

| Setting | Run by | For |
|---|---|---|
| `pandoc_command`, `html_pandoc_command` | `PandocConverter` | Converting Markdown, with the repository's filters |
| `setup.requires`, `setup.steps`, `setup.remotes` | `setting_up` | Executables to check, the repository's own setup steps, the publish remotes to add |
| `labs.gpu.hooks` | `labs.gpu` | Local commands before and after a notebook's run on a GPU machine |
| `labs.outputs.hooks` | `labs.outputs` | Commands run on a notebook's executed outputs before writing them back |
| `ci` | `hooks_install.ci_workflow` | The CI workflow's checks and builds |

A manual step that must follow a deckz command becomes one of these hooks, not a step
people have to remember.

## What a repository imports from deckz

The plugins and the repository's scripts import part of deckz. That part is deckz's
public API: changing it breaks a repository, so a change to it is a breaking change of
deckz, and plugins have `HOOKS_VERSION` for incompatible changes of the hooks' contract.
In shuuchuu/slides, the plugins and scripts import:

| Module | Names |
|---|---|
| `deckz.components.protocols` | `AssetsBuilderProtocol`, `CompilerProtocol` |
| `deckz.components.typst_figures_builder` | `TypstFiguresAssetsBuilder` |
| `deckz.configuring.settings` | `GlobalSettings` |
| `deckz.exceptions` | `DeckzError` |
| `deckz.models` | `File`, `Node`, `NodeInclude`, `Section`, `SectionDefinition`, `SectionInclude`… |
| `deckz.stamps` | `digest`, `is_fresh`, `python_sources`, `write_stamp` |
| `deckz.utils` | `all_decks`, `load_yaml`, `copy_file_if_changed`, `import_module_and_submodules` |
| `deckz.videos` | `register_scene`, `scenes`, `renders`, `video_file`, `quality`, `site_path`, `fetch_published`, `published_blobs`, `unpublished_reason` |
| `deckz.labs.notebook` | `canonical_dump` |

To check what a repository uses before changing one of these names, run `git grep -E
"(from|import) deckz"` in the repository.
