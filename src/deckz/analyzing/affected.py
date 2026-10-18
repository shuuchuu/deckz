"""Which decks a change to some files reaches: `deckz show affected`.

A deck is affected by a file it resolves (in French; an English file counts
as its French sibling, which every English build mirrors), or by any file
under its own directory (`deck.yml`, `variables.yml`, its local content).
"""

from collections.abc import Callable, Iterable
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..components.checks import Finding
    from ..configuring.settings import DeckSettings


def _french(path: Path) -> Path:
    # `content/x/en/a.md` -> `content/x/a.md`: decks are resolved in French.
    return path.parent.parent / path.name if path.parent.name == "en" else path


def deck_files(settings: "DeckSettings") -> set[Path]:
    """The files the deck of `settings` resolves to, in French.

    Returns:
        Their absolute paths, empty if the deck doesn't parse.
    """
    from ..components.deck_builder import PartDependenciesNodeVisitor
    from ..components.factory import DeckSettingsFactory
    from ..exceptions import DeckzError

    try:
        deck = (
            DeckSettingsFactory(settings, lang="fr")
            .parser()
            .from_deck_definition(settings.paths.deck_definition)
        )
    except DeckzError:
        return set()
    return {
        Path(dependency)
        for part in PartDependenciesNodeVisitor().process(deck).values()
        for dependency in part
    }


def reaches(settings: "DeckSettings") -> Callable[[PurePath], bool]:
    """Whether a change to a path reaches the deck of `settings`.

    Returns:
        The test, taking a path absolute or relative to the repository: \
        under the deck's directory, or a file it resolves (an English file \
        as its French sibling).
    """
    git_dir = settings.paths.git_dir
    deck_dir = settings.paths.current_dir.resolve()
    files = {path.resolve() for path in deck_files(settings)}

    def test(path: PurePath) -> bool:
        target = _french(git_dir / path).resolve()
        return target.is_relative_to(deck_dir) or target in files

    return test


def deck_findings(
    settings: "DeckSettings", findings: Iterable["Finding"]
) -> list["Finding"]:
    """The checks' problems about the deck of `settings`' files (`reaches`).

    Returns:
        Them, in order. A problem naming no path is about no deck, nor one
        naming an asset (`asset-credits`): which decks show it isn't mapped.
    """
    test = reaches(settings)
    return [f for f in findings if f.path is not None and test(f.path)]


def affected_decks(git_dir: Path, paths: Iterable[Path]) -> list["DeckSettings"]:
    """Every deck of the repository a change to `paths` reaches.

    Args:
        git_dir: The repository's root.
        paths: Changed files, absolute or relative to `git_dir`.

    Returns:
        The decks' settings, in directory order.
    """
    from ..utils import all_deck_settings

    paths = list(paths)
    if not paths:
        return []
    affected = []
    for settings in all_deck_settings(git_dir):
        test = reaches(settings)
        if any(test(path) for path in paths):
            affected.append(settings)
    return affected
