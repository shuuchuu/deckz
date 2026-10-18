"""The Problems panel: what a workspace has left to fix, kept up to date.

Two sources:

- the workspace's `deckz status` (the content checks, what its changes leave
  to translate, labs and videos not published), run by the workspace's own
  deckz in the background (`studioz.background`), and again whenever the
  workspace's files changed since: the checks take some 10 s on a large
  repository;
- the deck on screen: its live build's failure (`studioz.watches`), the
  frames its last build shrank to fit the page and the header or footer
  lines it wrapped (`deckz.analyzing.overflow`, from what the build
  recorded).

Each problem names the file, and line, it's about when it can, so that a
page can open it in the editor; a lab notebook's links to its page.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from deckz.analyzing.overflow import shrunk_frames, wrapped_lines
from deckz.configuring.settings import DeckSettings
from deckz.exceptions import DeckzError
from deckz.models import Lang

from . import sources
from .background import Report, Runs, fingerprint, git
from .watches import Snapshot, State

# `deckz status`'s sections shown, by key. Its built decks not matching their
# content are for building and uploading, not a problem while editing (and
# `status_command` doesn't ask for them).
_TITLES = {
    "checks": "Vérifications",
    "translation": "Traduction",
    "labs": "Labs",
    "videos": "Vidéos",
}
_LOCATION = re.compile(r"(?P<file>[^\s:'\"`()]+\.(?:md|yml))(?::(?P<line>\d+))?")
_NOTEBOOK = re.compile(r"(?P<file>[^\s:'\"`()]+)-(?P<lang>[a-z]+)\.ipynb")
# A pair of notebooks, as `lab-pairs` names it: `<lab>/<kind>: …`.
_PAIR = re.compile(r"(?P<file>[^\s:'\"`()]+/[^\s:'\"`()./]+):")


@dataclass(frozen=True)
class Problem:
    text: str
    fix: str = ""
    """How to resolve it, when deckz says."""
    file: str | None = None
    """The workspace's file it's about, one the editor opens."""
    line: int | None = None
    page: int | None = None
    """The page of the deck's handout it's about."""
    notebook: str | None = None
    """The lab notebook it's about, as its page names it: `<lab>/<kind>?lang=…`."""


@dataclass(frozen=True)
class Group:
    title: str
    problems: tuple[Problem, ...]
    key: str = ""
    """`deckz status`'s section key, for its groups."""


StatusReport = Report[tuple[Group, ...]]


def locate(workspace: Path, text: str) -> tuple[str | None, int | None]:
    """The first file `text` names that the editor opens, and its line.

    Returns:
        The file, relative to the workspace, and the line if named, or \
        `(None, None)`.
    """
    for match in _LOCATION.finditer(text):
        file = match["file"]
        if Path(file).is_absolute():
            try:
                file = Path(file).relative_to(workspace).as_posix()
            except ValueError:
                continue
        if sources.source(workspace, file) is not None:
            return file, int(match["line"]) if match["line"] else None
    return None, None


def notebook(text: str, labs_dir: Path | None) -> str | None:
    """The first lab notebook, or pair of notebooks, `text` names, as its page names it.

    Args:
        text: A problem.
        labs_dir: The notebooks' directory, relative to the workspace.

    Returns:
        Its lab and kind, and its language (`nlp/embeddings/demo?lang=fr`), \
        or None.
    """
    if labs_dir is None:
        return None
    found = [(m.start(), m["file"], m["lang"]) for m in _NOTEBOOK.finditer(text)]
    found += [(m.start(), m["file"], "fr") for m in _PAIR.finditer(text)]
    for _, file, lang in sorted(found):
        stem = Path(file)
        if stem.is_relative_to(labs_dir) and ".." not in stem.parts:
            return f"{stem.relative_to(labs_dir).as_posix()}?lang={lang}"
    return None


def status_command(workspace: Path, since: str | None) -> list[str]:
    """`deckz status` of a workspace, by its own deckz.

    Returns:
        The command, to run in the workspace.
    """
    # The built decks, slow to compare, aren't shown (`_TITLES`).
    deckz = str(workspace / ".venv" / "bin" / "deckz")
    command = [deckz, "status", "--json", "--no-decks"]
    return [*command, "--since", since] if since else command


def _groups(
    workspace: Path, sections: list[dict], labs_dir: Path | None = None
) -> tuple[Group, ...]:
    groups = []
    for section in sections:
        key = section.get("key", "")
        title = _TITLES.get(key)
        if title is None or not section["items"]:
            continue
        problems = []
        for item in section["items"]:
            file, line = locate(workspace, item["text"])
            problems.append(
                Problem(
                    item["text"],
                    item.get("fix", ""),
                    file,
                    line,
                    notebook=notebook(item["text"], labs_dir),
                )
            )
        groups.append(Group(title, tuple(problems), key))
    return tuple(groups)


def renders(workspace: Path, videos_dir: Path) -> tuple[str, ...]:
    """What the videos' renders look like, cheaply: git ignores them.

    Returns:
        Each render's stamp and quality file, with its time and size.
    """
    root = workspace / videos_dir
    found = []
    for path in sorted(root.rglob("*")) if root.is_dir() else ():
        if path.suffix in {".stamp", ".quality"}:
            stat = path.stat()
            found.append(f"{path.relative_to(root)}\0{stat.st_mtime_ns}")
    return tuple(found)


class Statuses(Runs[tuple[Group, ...]]):
    """Each workspace's `deckz status`, run again when its files change.

    Its renders included: whether a video is a draft depends on them.
    """

    def __init__(
        self,
        base: str | None,
        command=status_command,
        videos_dir: Path | None = None,
        labs_dir: Path | None = None,
    ) -> None:
        """Prepare the runs.

        Args:
            base: What workspaces' changes are counted from (their merge \
                base with it): the branch they sync with.
            command: `status_command`, which tests replace.
            videos_dir: The renders' directory, relative to a workspace.
            labs_dir: The lab notebooks' directory, relative to a workspace.
        """

        def run(workspace: Path) -> list[str]:
            since = git(workspace, "merge-base", "HEAD", base) if base else None
            return command(workspace, since)

        super().__init__(
            run,
            lambda workspace, out: _groups(
                workspace, json.loads(out)["sections"], labs_dir
            ),
            lambda workspace: (
                *fingerprint(workspace),
                *(renders(workspace, videos_dir) if videos_dir else ()),
            ),
        )


def build_problems(workspace: Path, snapshot: Snapshot) -> Group | None:
    """The live build's failure, if it failed.

    Returns:
        Its group, None unless the last build failed.
    """
    if snapshot.state is not State.FAILED or not snapshot.errors:
        return None
    text = "\n".join(snapshot.errors)
    file, line = locate(workspace, text)
    # deckz names files by their absolute path.
    text = text.replace(f"{workspace}/", "")
    return Group("Construction", (Problem(text, file=file, line=line),))


def _ratio(ratio: str) -> str:
    return ratio.replace("%", " %").replace(".", ",")


def shrunk(workspace: Path, deck: Path, lang: Lang) -> Group | None:
    """The frames the deck's last handout build shrank to fit their page.

    Returns:
        Their group, None if there's none or no build recorded them.
    """
    try:
        found = shrunk_frames(DeckSettings.from_yaml(deck), lang=lang, query=False)
    except DeckzError:
        return None
    problems = []
    for frame in found:
        file = frame.sources[0] if len(frame.sources) == 1 else None
        if file is not None and sources.source(workspace, file) is None:
            file = None
        problems.append(
            Problem(
                f"p. {frame.page} « {frame.title} » réduit à {_ratio(frame.ratio)}",
                file=file,
                line=frame.line if file else None,
                page=frame.page,
            )
        )
    return Group("Cadres réduits pour tenir", tuple(problems)) if problems else None


# The header and footer lines the theme marks, by its name for them.
_LINES = {
    "header breadcrumb": "Fil d'Ariane",
    "frame title": "Titre du cadre",
    "footer": "Pied de page",
}


def _pages(pages: tuple[int, ...]) -> str:
    shown = ", ".join(str(page) for page in pages[:5])
    more = f" et {len(pages) - 5} autres" if len(pages) > 5 else ""
    return f"p. {shown}{more}"


def wrapped(workspace: Path, deck: Path, lang: Lang) -> Group | None:
    """The header and footer lines the deck's last handout build wrapped.

    Returns:
        Their group, None if there's none or no build recorded them.
    """
    try:
        found = wrapped_lines(DeckSettings.from_yaml(deck), lang=lang, query=False)
    except DeckzError:
        return None
    problems = []
    for line in found or ():
        file, _, number = (line.source or "").rpartition(":")
        if not file or sources.source(workspace, file) is None:
            file = ""
        name = _LINES.get(line.line, line.line)
        problems.append(
            Problem(
                f"{_pages(line.pages)} {name} sur deux lignes ({_ratio(line.ratio)})"
                f" : « {line.text} »",
                fix=line.fix,
                file=file or None,
                line=int(number) if file else None,
                page=line.pages[0],
            )
        )
    return Group("Lignes sur deux lignes", tuple(problems)) if problems else None
