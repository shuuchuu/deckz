"""Generic, repository-wide content checks deckz can verify by itself.

Nothing here depends on a repo's theme or content conventions.


Each check is a `(settings) -> list[str]` function, its problems already
formatted as a human-readable line (commonly `"<path>: <message>"` or
`"<path>:<line>: <message>"`). `CHECKS` maps every built-in check's name to
its function, and `DEFERRED` those whose findings don't block a commit by
default. `deckz check content` is the CLI for this; a target repo can add
its own checks, in the
same shape, from a `templates/checks.py` plugin (see
[`checks`][deckz.components.checks] for how the two are merged).

What's generic enough to live here, as opposed to a repo's own theme/content
conventions (e.g. a markdown-guide.md frame pattern), is deliberately
narrow: every check below only relies on conventions deckz itself already
knows about (the content/labs directory layout, `labs.*` settings, the
Markdown-to-Typst/HTML pipeline, asset metadata yaml files).
"""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..exceptions import LabIdConflictError
from ..labs.comparison import compare_pairs, missing_notebooks
from ..labs.ids import assign_ids
from ..labs.notebook import notebook_paths
from ..utils import content_dirs

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings, GlobalSettings

_CREDIT_LINE = re.compile(r"^\s*(title|author|license)(_en)?\s*:.*\\[a-zA-Z{]")
_LATEX_BLOCK = re.compile(r"^[ \t]*```+[ \t]*\{=latex\}", re.MULTILINE)


def _rel(path: Path, git_dir: Path) -> str:
    return path.relative_to(git_dir).as_posix()


def lab_ids(settings: "GlobalSettings") -> list[str]:
    # Every lab notebook has a valid, unique ID (see `deckz labs ids`).
    paths = settings.paths
    try:
        missing = assign_ids(
            paths.labs_notebooks_dir,
            paths.content_dir,
            id_metadata_key=settings.labs.id_metadata_key,
            id_pattern=settings.labs.id_pattern,
            dry_run=True,
        )
    except LabIdConflictError as error:
        return [str(error)]
    return [
        f"{_rel(path, paths.git_dir)}: no valid ID (run `deckz labs ids`)"
        for _, path in missing
    ]


def lab_pairs(settings: "GlobalSettings") -> list[str]:
    # Every lab notebook exists in fr and en, and each pair stays in sync.
    notebooks_dir = settings.paths.labs_notebooks_dir
    git_dir = settings.paths.git_dir
    problems = [
        f"{_rel(notebooks_dir / path, git_dir)}: missing: translate the other "
        "language's notebook into it (a copy without its ID metadata, then "
        "`deckz labs ids`)"
        for path in missing_notebooks(notebooks_dir)
    ]
    for stem, pair_problems in compare_pairs(notebooks_dir):
        where = _rel(notebooks_dir / stem, git_dir)
        lab_dir = _rel((notebooks_dir / stem).parent, git_dir)
        problems += [
            f"{where}: {problem} (fr and en differ beyond a translation: "
            f"`deckz labs compare {lab_dir}`)"
            for problem in pair_problems
        ]
    return problems


def lab_outputs(settings: "GlobalSettings") -> list[str]:
    # A hands-on notebook never carries stored outputs (every learner runs
    # it); a demo always does, each language's from its own run, unless it
    # has no code to run, and never sets Colab's private outputs ("Omit code
    # cell output when saving"), which also hides them when Colab opens it.
    notebooks_dir = settings.paths.labs_notebooks_dir
    git_dir = settings.paths.git_dir
    problems = []
    for path in notebook_paths([notebooks_dir]):
        kind, _, _lang = path.stem.rpartition("-")
        if kind not in {"hands-on", "demo"}:
            continue
        notebook = json.loads(path.read_text(encoding="utf-8"))
        cells = notebook.get("cells", [])
        code_cells = [cell for cell in cells if cell.get("cell_type") == "code"]
        has_outputs = any(cell.get("outputs") for cell in code_cells)
        where = _rel(path, git_dir)
        if kind == "hands-on" and has_outputs:
            problems.append(
                f"{where}: hands-on notebook has stored outputs: clear them "
                f"(`jupyter nbconvert --clear-output --inplace {where}`, then "
                f"`deckz labs fmt {where}`)"
            )
        elif kind == "demo" and code_cells and not has_outputs:
            problems.append(
                f"{where}: demo notebook has no stored outputs: run it, then "
                f"`deckz labs outputs <executed copy> {where}`"
            )
        elif kind == "demo" and (blank := _blank_output_cells(cells)):
            numbers = ", ".join(f"[{i}]" for i in blank)
            problems.append(
                f"{where}: demo notebook cells {numbers} (as `deckz labs dump` "
                "numbers them) store outputs that are only whitespace: run it "
                f"again, then `deckz labs outputs <executed copy> {where}`"
            )
        colab = notebook.get("metadata", {}).get("colab", {})
        if kind == "demo" and colab.get("private_outputs"):
            problems.append(
                f"{where}: demo notebook sets Colab's private_outputs, which "
                "hides its stored outputs: remove metadata.colab.private_outputs "
                "(Colab: Edit > Notebook settings)"
            )
    return problems


def _blank_output_cells(cells: list[dict[str, Any]]) -> list[int]:
    # The code cells whose stored outputs show nothing: each one text (a
    # stream, or a result with only `text/*` data) of whitespace alone, as
    # `deckz labs outputs` once wrote for `\r\n` lines. A cell without any
    # output (imports, definitions) is fine, and so is one with an image or
    # an error next to blank text.
    return [
        i
        for i, cell in enumerate(cells)
        if cell.get("cell_type") == "code"
        and cell.get("outputs")
        and all(_blank_text_output(output) for output in cell["outputs"])
    ]


def _blank_text_output(output: dict[str, Any]) -> bool:
    output_type = output.get("output_type")
    if output_type == "stream":
        texts = [output.get("text", "")]
    elif output_type in {"execute_result", "display_data"}:
        data = output.get("data", {})
        if not data or any(not mime.startswith("text/") for mime in data):
            return False
        texts = list(data.values())
    else:
        return False
    return all(
        not "".join(text if isinstance(text, list) else [text]).strip()
        for text in texts
    )


def _notebooks(settings: "GlobalSettings") -> list[Path]:
    # A repository may have no labs at all.
    notebooks_dir = settings.paths.labs_notebooks_dir
    return list(notebook_paths([notebooks_dir])) if notebooks_dir.is_dir() else []


def lab_secrets(settings: "GlobalSettings") -> list[str]:
    # The labs are published to a public repository: no token in a cell's
    # source, nor printed in its stored outputs.
    from ..labs.secrets import find_secrets

    git_dir = settings.paths.git_dir
    problems = []
    for path in _notebooks(settings):
        notebook = json.loads(path.read_text(encoding="utf-8"))
        problems += [
            f"{_rel(path, git_dir)}: {finding}: remove it, revoke it if it was "
            "real, and list it in labs.not_secrets if it isn't a secret"
            for finding in find_secrets(notebook, settings.labs.not_secrets)
        ]
    return problems


def lab_format(settings: "GlobalSettings") -> list[str]:
    # Every notebook is in deckz's canonical JSON style, so that a small edit
    # stays a small diff (a notebook saved from Colab comes back compact).
    from ..labs.notebook import fmt_notebook

    git_dir = settings.paths.git_dir
    return [
        f"{_rel(path, git_dir)}: not in deckz's notebook format: run "
        f"`deckz labs fmt {_rel(path, git_dir)}`"
        for path in _notebooks(settings)
        if fmt_notebook(path, heading=settings.labs.solution_heading, dry_run=True)
    ]


def asset_credits(settings: "GlobalSettings") -> list[str]:
    # Asset credit lines (title/author/license, and their _en) are Markdown,
    # rendered through the same pipeline as content, which drops LaTeX.
    git_dir = settings.paths.git_dir
    problems = []
    for path in sorted(settings.paths.assets_dir.rglob("*.yml")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _CREDIT_LINE.match(line):
                where = f"{_rel(path, git_dir)}:{lineno}"
                problems.append(
                    f"{where}: LaTeX in a credit line: {line.strip()}: write it "
                    "in Markdown (`code`, *italic*, **bold**, plain characters)"
                )
    return problems


def raw_latex(settings: "GlobalSettings") -> list[str]:
    # No .tex content file, no {=latex} block: the Markdown pipeline drops both.
    git_dir = settings.paths.git_dir
    content_dir = settings.paths.content_dir
    problems = []
    for a_content_dir in content_dirs(git_dir, content_dir):
        if not a_content_dir.is_dir():
            continue
        for path in sorted(a_content_dir.rglob("*.tex")):
            problems.append(
                f"{_rel(path, git_dir)}: .tex content (only "
                f"{', '.join(settings.file_extensions)} is compiled): convert "
                "it to Markdown"
            )
        for extension in settings.file_extensions:
            for path in sorted(a_content_dir.rglob(f"*{extension}")):
                text = path.read_text(encoding="utf-8")
                for match in _LATEX_BLOCK.finditer(text):
                    lineno = text.count("\n", 0, match.start()) + 1
                    where = f"{_rel(path, git_dir)}:{lineno}"
                    problems.append(
                        f"{where}: {{=latex}} block (dropped by the Markdown "
                        "pipeline): rewrite it in Markdown, or as a {=typst} block"
                    )
    return problems


def jinja_syntax(settings: "GlobalSettings") -> list[str]:
    # Every content file parses with the repository's own Jinja environment
    # (`templates/jinja2/env.py`), the one a build renders it with, its
    # filters and tests known to it: a broken tag (`{{ x`) or a misspelt
    # filter fails here rather than at the next build. That needs no deck's
    # variables, as rendering would; and checking the names is what compiling
    # adds, in a third of its time (1,500 files in 0.4 s).
    from jinja2 import TemplateSyntaxError, nodes

    from ..components.factory import GlobalSettingsFactory
    from ..exceptions import HookError

    paths = settings.paths
    if not paths.jinja2_env_module.is_file():
        return []  # Nothing renders without one.
    renderer = GlobalSettingsFactory(settings).renderer()
    problems = []
    for a_content_dir in content_dirs(paths.git_dir, paths.content_dir):
        if not a_content_dir.is_dir():
            continue
        for extension in settings.file_extensions:
            for path in sorted(a_content_dir.rglob(f"*{extension}")):
                where = _rel(path, paths.git_dir)
                try:
                    env = renderer.environment_for(path.suffix)
                    ast = env.parse(path.read_text(encoding="utf-8"))
                except HookError as error:
                    return [str(error)]
                except TemplateSyntaxError as error:
                    problems.append(
                        f"{where}:{error.lineno}: {error.message}: fix the Jinja"
                        " tag, or put it inside {% raw %}…{% endraw %} if it's"
                        " meant as text"
                    )
                    continue
                for node in ast.find_all((nodes.Filter, nodes.Test)):
                    kind, known = (
                        ("filter", env.filters)
                        if isinstance(node, nodes.Filter)
                        else ("test", env.tests)
                    )
                    if node.name not in known:
                        problems.append(
                            f"{where}:{node.lineno}: no {kind} named"
                            f" {node.name!r} in templates/jinja2/env.py's"
                            f" environment: fix its name"
                        )
    return problems


def _deck_problems(settings: "DeckSettings") -> list[str]:
    from ..components.factory import DeckSettingsFactory
    from ..configuring.variables import get_variables
    from ..exceptions import DeckParsingError, DeckzError

    git_dir = settings.paths.git_dir
    definition = settings.paths.deck_definition
    where = _rel(definition, git_dir)
    try:
        DeckSettingsFactory(settings, lang="fr").parser().from_deck_definition(
            definition
        )
        get_variables(settings, "fr")
    except DeckParsingError as error:
        return [
            f"{where}: {problem.replace(f'{git_dir}/', '')}: fix the definition,"
            " or restore what it names"
            for problem in error.errors
        ]
    except DeckzError as error:
        message = str(error).replace(f"{git_dir}/", "")
        return [message if message.startswith(where) else f"{where}: {message}"]
    return []


def deck_definitions(settings: "GlobalSettings") -> list[str]:
    # Every deck parses in French, as its build would: its deck.yml, the
    # sections it includes and their flavors, the files they name, its
    # variables.yml. A deleted shared file still included, or a section
    # .yml that doesn't parse, fails here rather than in every build of
    # the decks using it. English is `missing-en`'s (a plugin's, slow).
    # About a second for 43 decks, in deckz's process pool.
    from ..exceptions import DeckzError
    from ..utils import all_deck_settings, create_pool

    git_dir = settings.paths.git_dir
    try:
        decks = list(all_deck_settings(git_dir))
    except DeckzError as error:
        return [str(error).replace(f"{git_dir}/", "")]
    if not decks:
        return []
    with create_pool(min(len(decks), 4)) as pool:
        found = pool.map(_deck_problems, decks)
    return [problem for deck in found for problem in deck]


def _published_notebooks_slug(settings: "GlobalSettings") -> str | None:
    # The owner/repo of labs.publish_remote, or None if it isn't configured.
    from pygit2 import GitError, Repository

    try:
        repo = Repository(str(settings.paths.git_dir))
        url = repo.remotes[settings.labs.publish_remote].url
    except (GitError, KeyError, ValueError):
        return None
    if url is None:
        return None
    match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", url)
    return match.group(1) if match else None


def lab_urls(settings: "GlobalSettings") -> list[str]:
    # No hand-written link to the published notebooks repo: a notebook's
    # published URL depends on its ID (deckz labs publish), which can be
    # reassigned, so a repo rendering it should do so through its own
    # templating, not a literal, rot-prone URL.
    slug = _published_notebooks_slug(settings)
    if slug is None:
        return []
    pattern = re.compile(re.escape(slug) + r"\b")
    git_dir = settings.paths.git_dir
    content_dir = settings.paths.content_dir
    problems = []
    for a_content_dir in content_dirs(git_dir, content_dir):
        if not a_content_dir.is_dir():
            continue
        for extension in settings.file_extensions:
            for path in sorted(a_content_dir.rglob(f"*{extension}")):
                text = path.read_text(encoding="utf-8")
                for lineno, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        where = f"{_rel(path, git_dir)}:{lineno}"
                        problems.append(
                            f"{where}: hand-written link to the "
                            "published notebooks repo: link the lab through the "
                            "repository's own templating, which follows its ID"
                        )
    return problems


CHECKS: dict[str, Callable[["GlobalSettings"], list[str]]] = {
    "lab-ids": lab_ids,
    "lab-pairs": lab_pairs,
    "lab-outputs": lab_outputs,
    "lab-secrets": lab_secrets,
    "lab-format": lab_format,
    "asset-credits": asset_credits,
    "raw-latex": raw_latex,
    "jinja-syntax": jinja_syntax,
    "deck-definitions": deck_definitions,
    "lab-urls": lab_urls,
}

DEFERRED = (
    "lab-ids",
    "lab-pairs",
    "lab-outputs",
    "lab-format",
    "asset-credits",
    "raw-latex",
    "lab-urls",
)
"""The built-in checks whose findings don't fail `deckz check` by default.

Their harm comes later than the commit (a lab published, a deck uploaded or
taught), so a contributor commits freely and the debt is settled before
then. Those left out block a commit, the point of their harm:
`lab-secrets` (a secret stays in the history), `jinja-syntax` and
`deck-definitions` (each `git pull` breaks everyone's builds). `deckz.yml`'s
`checks.deferred` replaces this list.
"""
