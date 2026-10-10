"""The Changes panel: what a workspace changed since its last commit.

Its changed files, grouped by what they are (a deck's own files, shared
content, labs, videos, images and theme, the rest), each content file or
notebook whose other language didn't change flagged: the commit hook asks
such a commit for a `Lang-sync` trailer. Then the decks the changes reach
(`deckz show affected`, 7 s on slides: run in the background by the
workspace's own deckz, again when the changed files, or a changed `.yml`,
change), each one's before/after (`studioz.comparison`) a click away.
"""

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from deckz.configuring.settings import GlobalSettings

from . import sources
from .background import Change, Runs, changes, git


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str
    """In French: modifié, nouveau, supprimé, renommé, en conflit."""
    other_lang: str | None = None
    """The other language's file, when it exists and didn't change."""
    editable: bool = False


@dataclass(frozen=True)
class ChangeGroup:
    title: str
    files: tuple[ChangedFile, ...]
    deck: str | None = None
    """The deck whose own files these are."""


def _status(code: str) -> str:
    if "U" in code or code in {"AA", "DD"}:
        return "en conflit"
    if "D" in code:
        return "supprimé"
    if "?" in code or "A" in code:
        return "nouveau"
    if "R" in code:
        return "renommé"
    return "modifié"


def other_lang(path: PurePosixPath) -> PurePosixPath | None:
    """The other language's version of a content file or lab notebook.

    deckz's conventions: `x/a.md` is translated in `x/en/a.md`, and
    `a-fr.ipynb` in `a-en.ipynb`.

    Returns:
        Its path, None for other files.
    """
    if path.suffix == ".md":
        if path.parent.name == "en":
            return path.parent.parent / path.name
        return path.parent / "en" / path.name
    for lang, other in (("fr", "en"), ("en", "fr")):
        suffix = f"-{lang}.ipynb"
        if path.name.endswith(suffix):
            return path.with_name(path.name.removesuffix(suffix) + f"-{other}.ipynb")
    return None


def _relative(workspace: Path, path: Path) -> PurePosixPath:
    return PurePosixPath(path.relative_to(workspace).as_posix())


def grouped(workspace: Path, decks: list[str]) -> list[ChangeGroup]:
    """The workspace's changes since its last commit, grouped.

    Args:
        workspace: The workspace.
        decks: Its decks (`studioz.workspaces.decks`).

    Returns:
        The groups with changes: each deck's own files first, by deck.
    """
    paths = GlobalSettings.from_yaml(workspace).paths
    found = changes(workspace)
    changed = {change.path for change in found}
    content_dirs = [_relative(workspace, paths.content_dir)] + [
        PurePosixPath(deck) / "content" for deck in decks
    ]
    kinds = [
        ("Contenu partagé", _relative(workspace, paths.content_dir)),
        ("Labs", _relative(workspace, paths.labs_notebooks_dir)),
        ("Vidéos", _relative(workspace, paths.scenes_dir)),
        ("Images et thème", _relative(workspace, paths.assets_dir)),
    ]
    by_deck: dict[str, list[ChangedFile]] = {}
    by_kind: dict[str, list[ChangedFile]] = {}
    for change in found:
        path = PurePosixPath(change.path)
        file = _file(workspace, change, path, changed, content_dirs)
        deck = max((d for d in decks if path.is_relative_to(d)), key=len, default=None)
        if deck is not None:
            by_deck.setdefault(deck, []).append(file)
            continue
        kind = next(
            (title for title, root in kinds if path.is_relative_to(root)),
            "Autres fichiers",
        )
        by_kind.setdefault(kind, []).append(file)
    groups = [
        ChangeGroup(deck, tuple(files), deck) for deck, files in sorted(by_deck.items())
    ]
    order = [title for title, _ in kinds] + ["Autres fichiers"]
    groups += [
        ChangeGroup(title, tuple(by_kind[title])) for title in order if title in by_kind
    ]
    return groups


def _file(
    workspace: Path,
    change: Change,
    path: PurePosixPath,
    changed: set[str],
    content_dirs: list[PurePosixPath],
) -> ChangedFile:
    sibling = other_lang(path)
    if (
        sibling is not None
        and path.suffix == ".md"
        and not any(path.is_relative_to(root) for root in content_dirs)
    ):
        sibling = None
    alone = (
        sibling is not None
        and str(sibling) not in changed
        and (workspace / sibling).exists()
    )
    return ChangedFile(
        change.path,
        _status(change.status),
        str(sibling) if alone else None,
        sources.source(workspace, change.path) is not None,
    )


def affected_command(workspace: Path) -> list[str] | None:
    """`deckz show affected` of the workspace's changes, by its own deckz.

    Returns:
        The command, to run in the workspace; None without changes.
    """
    found = changes(workspace)
    if not found:
        return None
    deckz = str(workspace / ".venv" / "bin" / "deckz")
    return [deckz, "show", "affected", "--json", *(c.path for c in found)]


def affected_fingerprint(workspace: Path) -> tuple[str, ...]:
    """What the decks the changes reach depend on.

    Returns:
        HEAD, the changed files, and the changed `.yml` files' times (a \
        deck's or a section's definition).
    """
    found = []
    for change in changes(workspace):
        path = workspace / change.path
        stamp = ""
        if path.suffix == ".yml" and path.exists():
            stamp = str(path.stat().st_mtime_ns)
        found.append(f"{change.path}\0{stamp}")
    return (git(workspace, "rev-parse", "HEAD") or "", *sorted(found))


def _decks(_: Path, output: str) -> tuple[str, ...]:
    return tuple(str(deck) for deck in json.loads(output))


class Affected(Runs[tuple[str, ...]]):
    """The decks each workspace's changes reach, found again when they change."""

    def __init__(self, command=affected_command) -> None:
        """Prepare the runs.

        Args:
            command: `affected_command`, which tests replace.
        """
        super().__init__(command, _decks, affected_fingerprint)
