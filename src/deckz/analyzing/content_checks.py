"""Generic, repository-wide content checks deckz can verify by itself.

Nothing here depends on a repo's theme or content conventions.


Each check is a `(settings, paths=None) -> list[str]` function, its problems
already formatted as a human-readable line (commonly `"<path>: <message>"` or
`"<path>:<line>: <message>"`). Given `paths` (absolute paths, e.g. the files a
Claude Code hook checks), a check reports only about them, and returns at once
when none is of a kind it reads; without, it checks the whole repository.
`CHECKS` maps every built-in check's name to
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
from collections.abc import Callable, Collection, Iterable, Iterator
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from ..exceptions import LabIdConflictError
from ..labs.comparison import compare_pairs, missing_notebooks
from ..labs.ids import assign_ids
from ..labs.notebook import notebook_paths
from ..utils import content_dirs, content_files, is_content_file

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings, GlobalSettings

_CREDIT_LINE = re.compile(r"^\s*(title|author|license)(_en)?\s*:.*\\[a-zA-Z{]")
_LATEX_BLOCK = re.compile(r"^[ \t]*```+[ \t]*\{=latex\}", re.MULTILINE)


def _rel(path: Path, git_dir: Path) -> str:
    return path.relative_to(git_dir).as_posix()


Paths = Collection[Path] | None
"""The files a check is limited to, or None for the whole repository."""


def _any(paths: Paths, wanted: Callable[[Path], bool]) -> bool:
    # Whether a check reading the files `wanted` accepts has anything to do.
    return paths is None or any(wanted(path) for path in paths)


def _under(path: Path, directory: Path) -> bool:
    return path.is_relative_to(directory)


def _is_notebook(settings: "GlobalSettings", path: Path) -> bool:
    return path.suffix == ".ipynb" and _under(path, settings.paths.labs_notebooks_dir)


def _in_content_dir(settings: "GlobalSettings", path: Path) -> bool:
    # In the shared content directory, or in a deck's own (a `content/` next
    # to a `deck.yml`, `DeckPaths`' defaults): what `content_dirs` walks,
    # without parsing every deck.
    if _under(path, settings.paths.content_dir):
        return True
    return any(
        _under(parent, settings.paths.git_dir)
        and parent.name == "content"
        and (parent.parent / "deck.yml").is_file()
        for parent in path.parents
    )


def _content_files(settings: "GlobalSettings", paths: Paths) -> Iterator[Path]:
    # Every content file, or those of `paths` (existing, in a content directory).
    if paths is not None:
        yield from (
            path
            for path in sorted(paths)
            if is_content_file(path, settings.file_extensions)
            and path.is_file()
            and _in_content_dir(settings, path)
        )
        return
    git_dir = settings.paths.git_dir
    for a_content_dir in content_dirs(git_dir, settings.paths.content_dir):
        if a_content_dir.is_dir():
            yield from content_files(a_content_dir, settings.file_extensions)


def lab_ids(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # Every lab notebook has a valid, unique ID (see `deckz labs ids`).
    if not _any(paths, lambda path: _is_notebook(settings, path)):
        return []
    dirs = settings.paths
    try:
        missing = assign_ids(
            dirs.labs_notebooks_dir,
            dirs.content_dir,
            id_metadata_key=settings.labs.id_metadata_key,
            id_pattern=settings.labs.id_pattern,
            dry_run=True,
        )
    except LabIdConflictError as error:
        return [str(error)]
    return [
        f"{_rel(path, dirs.git_dir)}: no valid ID (run `deckz labs ids`)"
        for _, path in missing
    ]


def lab_pairs(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # Every lab notebook exists in fr and en, and each pair stays in sync.
    if not _any(paths, lambda path: _is_notebook(settings, path)):
        return []
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


def lab_outputs(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # A hands-on notebook never carries stored outputs (every learner runs
    # it); a demo always does, each language's from its own run, unless it
    # has no code to run, and never sets Colab's private outputs ("Omit code
    # cell output when saving"), which also hides them when Colab opens it.
    git_dir = settings.paths.git_dir
    problems = []
    for path in _notebooks(settings, paths):
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


def _notebooks(settings: "GlobalSettings", paths: Paths = None) -> list[Path]:
    # A repository may have no labs at all.
    if paths is not None:
        return [
            path
            for path in sorted(paths)
            if _is_notebook(settings, path) and path.is_file()
        ]
    notebooks_dir = settings.paths.labs_notebooks_dir
    return list(notebook_paths([notebooks_dir])) if notebooks_dir.is_dir() else []


def lab_secrets(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # The labs are published to a public repository: no token in a cell's
    # source, nor printed in its stored outputs.
    from ..labs.secrets import find_secrets

    git_dir = settings.paths.git_dir
    problems = []
    for path in _notebooks(settings, paths):
        notebook = json.loads(path.read_text(encoding="utf-8"))
        problems += [
            f"{_rel(path, git_dir)}: {finding}: remove it, revoke it if it was "
            "real, and list it in labs.not_secrets if it isn't a secret"
            for finding in find_secrets(notebook, settings.labs.not_secrets)
        ]
    return problems


def lab_format(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # Every notebook is in deckz's canonical JSON style, so that a small edit
    # stays a small diff (a notebook saved from Colab comes back compact).
    from ..labs.notebook import fmt_notebook

    git_dir = settings.paths.git_dir
    return [
        f"{_rel(path, git_dir)}: not in deckz's notebook format: run "
        f"`deckz labs fmt {_rel(path, git_dir)}`"
        for path in _notebooks(settings, paths)
        if fmt_notebook(path, heading=settings.labs.solution_heading, dry_run=True)
    ]


def asset_credits(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # Asset credit lines (title/author/license, and their _en) are Markdown,
    # rendered through the same pipeline as content, which drops LaTeX.
    git_dir = settings.paths.git_dir
    assets_dir = settings.paths.assets_dir
    found: Iterable[Path] = (
        assets_dir.rglob("*.yml")
        if paths is None
        else (
            path
            for path in paths
            if path.suffix == ".yml" and _under(path, assets_dir) and path.is_file()
        )
    )
    problems = []
    for path in sorted(found):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _CREDIT_LINE.match(line):
                where = f"{_rel(path, git_dir)}:{lineno}"
                problems.append(
                    f"{where}: LaTeX in a credit line: {line.strip()}: write it "
                    "in Markdown (`code`, *italic*, **bold**, plain characters)"
                )
    return problems


def raw_latex(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # No .tex content file, no {=latex} block: the Markdown pipeline drops both.
    git_dir = settings.paths.git_dir
    if paths is None:
        tex = [
            path
            for a_content_dir in content_dirs(git_dir, settings.paths.content_dir)
            if a_content_dir.is_dir()
            for path in sorted(a_content_dir.rglob("*.tex"))
        ]
    else:
        tex = [
            path
            for path in sorted(paths)
            if path.suffix == ".tex" and _in_content_dir(settings, path)
        ]
    problems = [
        f"{_rel(path, git_dir)}: .tex content (only "
        f"{', '.join(settings.file_extensions)} is compiled): convert "
        "it to Markdown"
        for path in tex
    ]
    for path in _content_files(settings, paths):
        text = path.read_text(encoding="utf-8")
        for match in _LATEX_BLOCK.finditer(text):
            lineno = text.count("\n", 0, match.start()) + 1
            where = f"{_rel(path, git_dir)}:{lineno}"
            problems.append(
                f"{where}: {{=latex}} block (dropped by the Markdown "
                "pipeline): rewrite it in Markdown, or as a {=typst} block"
            )
    return problems


def jinja_syntax(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # Every content file parses with the repository's own Jinja environment
    # (`templates/jinja2/env.py`), the one a build renders it with, its
    # filters and tests known to it: a broken tag (`{{ x`) or a misspelt
    # filter fails here rather than at the next build. That needs no deck's
    # variables, as rendering would; and checking the names is what compiling
    # adds, in a third of its time (1,500 files in 0.4 s).
    from jinja2 import TemplateSyntaxError, nodes

    from ..components.factory import GlobalSettingsFactory
    from ..exceptions import HookError

    if not settings.paths.jinja2_env_module.is_file():
        return []  # Nothing renders without one.
    files = list(_content_files(settings, paths))
    if not files:
        return []
    git_dir = settings.paths.git_dir
    renderer = GlobalSettingsFactory(settings).renderer()
    problems = []
    for path in files:
        where = _rel(path, git_dir)
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


def deck_definitions(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # Every deck parses in French, as its build would: its deck.yml, the
    # sections it includes and their flavors, the files they name, its
    # variables.yml. A deleted shared file still included, or a section
    # .yml that doesn't parse, fails here rather than in every build of
    # the decks using it. English is `missing-en`'s (a plugin's, slow).
    # About a second for 43 decks, in deckz's process pool. Of `paths`,
    # only a YAML file changes what parses: an existing content file can't.
    from ..exceptions import DeckzError
    from ..utils import all_deck_settings, create_pool

    if not _any(paths, lambda path: path.suffix in {".yml", ".yaml"}):
        return []
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


def lab_urls(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # No hand-written link to the published notebooks repo: a notebook's
    # published URL depends on its ID (deckz labs publish), which can be
    # reassigned, so a repo rendering it should do so through its own
    # templating, not a literal, rot-prone URL.
    slug = _published_notebooks_slug(settings)
    if slug is None:
        return []
    pattern = re.compile(re.escape(slug) + r"\b")
    git_dir = settings.paths.git_dir
    problems = []
    for path in _content_files(settings, paths):
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


def _course_notes_touched(settings: "GlobalSettings", paths: Paths) -> bool:
    # A chapter, or deckz.yml (`course_notes.same_as`), among `paths`.
    return _any(
        paths,
        lambda path: (
            _under(path, settings.paths.course_notes_dir) or path.name == "deckz.yml"
        ),
    )


def course_notes_files(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # Each course notes chapter writes out an existing shared content file, at
    # its path, and `course_notes.same_as` names content files, none of which
    # has a chapter of its own (see `deckz.course_notes`).
    from ..course_notes import chapter_path, chapters

    if not _course_notes_touched(settings, paths):
        return []
    content_dir = settings.paths.content_dir
    git_dir = settings.paths.git_dir
    extension = settings.file_extensions[0] if settings.file_extensions else ".md"

    def exists(path: str) -> bool:
        return (content_dir / f"{path}{extension}").is_file()

    found = list(chapters(settings))
    problems = [
        f"{_rel(chapter_path(settings, path, lang), git_dir)}: no "
        f"{_rel(content_dir, git_dir)}/{path}{extension}: name a chapter "
        "after the content file it writes out (move it after a renamed one)"
        for path, lang in found
        if not exists(path)
    ]
    written = {path for path, _ in found}
    for path, target in settings.course_notes.same_as.items():
        problems.extend(
            f"deckz.yml: course_notes.same_as {path}: no content file {name}"
            for name in (path, target)
            if not exists(name)
        )
        if path in written:
            problems.append(
                f"{_rel(chapter_path(settings, path, 'fr'), git_dir)}: "
                f"course_notes.same_as says {target}'s chapter covers {path}: "
                "remove one of them"
            )
    return problems


def course_notes_pairs(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # Each course notes chapter exists in fr and en. A directory with French
    # chapters and no English one at all is a unit still being written or not
    # translated yet, not a forgotten file: it gets one line, about the
    # directory, and none with `paths` (the post-edit hook's, on each edit of
    # a chapter being drafted). Once the directory has an English chapter, each
    # missing one is a line of its own, `paths` or not.
    from ..course_notes import course_notes_pairs as pairs

    if not _course_notes_touched(settings, paths):
        return []
    git_dir = settings.paths.git_dir
    touched = (
        None
        if paths is None or any(path.name == "deckz.yml" for path in paths)
        else {path.resolve() for path in paths}
    )
    problems = []
    untranslated: dict[PurePosixPath, list[PurePosixPath]] = {}
    for fr, en in pairs(settings):
        if (
            touched is not None
            and not {
                (git_dir / fr).resolve(),
                (git_dir / en).resolve(),
            }
            & touched
        ):
            continue
        if (git_dir / en).is_file() and not (git_dir / fr).is_file():
            problems.append(f"{en}: no French version ({fr})")
        elif (git_dir / fr).is_file() and not (git_dir / en).is_file():
            if _has_chapter(settings, git_dir / en.parent):
                problems.append(f"{fr}: no English version ({en})")
            else:
                untranslated.setdefault(fr.parent, []).append(fr)
    if touched is None:
        problems.extend(
            f"{directory}: {len(chapters)} French chapter(s) and no English one "
            f"yet ({', '.join(chapter.name for chapter in chapters)}): translate "
            f"them into {directory / 'en'}"
            for directory, chapters in untranslated.items()
        )
    return sorted(problems)


def course_notes_code(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # Each course notes chapter's Python code runs, and prints what the
    # chapter shows it printing (see `deckz.course_notes_code`). Opt-in: it
    # runs the chapters' code, with their libraries, for minutes.
    from ..course_notes import chapter_path, chapters
    from ..course_notes_code import check_chapters, unmatched_patterns

    if not _any(paths, lambda path: _under(path, settings.paths.course_notes_dir)):
        return []
    every = [chapter_path(settings, path, lang) for path, lang in chapters(settings)]
    if paths is None:
        return unmatched_patterns(settings, every) + check_chapters(settings, every)
    wanted = {path.resolve() for path in paths}
    return check_chapters(
        settings, [chapter for chapter in every if chapter.resolve() in wanted]
    )


def _has_chapter(settings: "GlobalSettings", directory: Path) -> bool:
    # Whether `directory` (a chapters' `en/`) holds a chapter.
    return directory.is_dir() and any(
        content_files(directory, settings.file_extensions)
    )


def review_headers(settings: "GlobalSettings", paths: Paths = None) -> list[str]:
    # Every review report's `reviewed` front matter is well formed, and the
    # files it records exist (see `deckz.analyzing.review`). Nothing to do
    # without `review.dir`. A rename or deletion of a recorded file shows
    # in the whole-repository run (the pre-commit hook's): the hooks' paths
    # are the files edited, never the one gone.
    from .review import header_problems

    return header_problems(settings, paths)


CHECKS: dict[str, Callable[["GlobalSettings", Paths], list[str]]] = {
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
    "course-notes-files": course_notes_files,
    "course-notes-pairs": course_notes_pairs,
    "course-notes-code": course_notes_code,
    "review-headers": review_headers,
}

DEFERRED = (
    "lab-ids",
    "lab-pairs",
    "lab-outputs",
    "lab-format",
    "asset-credits",
    "raw-latex",
    "lab-urls",
    "course-notes-files",
    "course-notes-pairs",
    "course-notes-code",
)
"""The built-in checks whose findings don't fail `deckz check` by default.

Their harm comes later than the commit (a lab published, a deck uploaded or
taught), so a contributor commits freely and the debt is settled before
then. Those left out block a commit, the point of their harm:
`lab-secrets` (a secret stays in the history), `jinja-syntax` and
`deck-definitions` (each `git pull` breaks everyone's builds), and
`review-headers` (a malformed report stops `deckz review` for everyone
after a pull, and a renamed file's review is best carried over by whoever
renames it). `deckz.yml`'s `checks.deferred` replaces this list.
"""

OPT_IN = ("course-notes-code",)
"""The built-in checks `deckz check` runs only when named.

`course-notes-code` runs every chapter's code, with the libraries
`course_notes.code.python` installs, for minutes: `deckz check
course-notes-code --file <chapter>` checks one chapter as it's written.
They stay opt-in whatever the repository sets: `deckz.yml`'s
`checks.opt_in` adds to them, so a repository listing its own opt-in checks
doesn't start running every chapter's code on each commit.
"""
