"""Generic, repository-wide content checks deckz can verify by itself.

Nothing here depends on a repo's theme or content conventions.


Each check is a `(settings) -> list[str]` function, its problems already
formatted as a human-readable line (commonly `"<path>: <message>"` or
`"<path>:<line>: <message>"`). `CHECKS` maps every built-in check's name to
its function; `run_checks` runs a selection of them (every one by default)
and returns each failing check's problems, keyed by name. `deckz check
content` is the CLI for this; a target repo can add its own checks, in the
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
from typing import TYPE_CHECKING

from ..exceptions import LabIdConflictError
from ..labs.comparison import compare_pairs, missing_notebooks
from ..labs.ids import assign_ids
from ..labs.notebook import notebook_paths
from ..utils import content_dirs

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings

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
        f"{_rel(notebooks_dir / path, git_dir)}: missing"
        for path in missing_notebooks(notebooks_dir)
    ]
    for stem, pair_problems in compare_pairs(notebooks_dir):
        where = _rel(notebooks_dir / stem, git_dir)
        problems += [f"{where}: {problem}" for problem in pair_problems]
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
            problems.append(f"{where}: hands-on notebook has stored outputs")
        elif kind == "demo" and code_cells and not has_outputs:
            problems.append(f"{where}: demo notebook has no stored outputs")
        colab = notebook.get("metadata", {}).get("colab", {})
        if kind == "demo" and colab.get("private_outputs"):
            problems.append(
                f"{where}: demo notebook sets Colab's private_outputs, which "
                "hides its stored outputs"
            )
    return problems


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
                problems.append(f"{where}: LaTeX in a credit line: {line.strip()}")
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
                f"{', '.join(settings.file_extensions)} is compiled)"
            )
        for extension in settings.file_extensions:
            for path in sorted(a_content_dir.rglob(f"*{extension}")):
                text = path.read_text(encoding="utf-8")
                for match in _LATEX_BLOCK.finditer(text):
                    lineno = text.count("\n", 0, match.start()) + 1
                    where = f"{_rel(path, git_dir)}:{lineno}"
                    problems.append(
                        f"{where}: {{=latex}} block (dropped by the Markdown pipeline)"
                    )
    return problems


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
                            "published notebooks repo"
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
    "lab-urls": lab_urls,
}
