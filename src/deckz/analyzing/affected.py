"""Which decks a change to some files reaches: `deckz show affected`.

A deck is affected by a file it resolves (in French; an English file counts
as its French sibling, which every English build mirrors), or by any file
under its own directory (`deck.yml`, `variables.yml`, its local content).
"""

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
        Path(dependency.resolved_path)
        for part in PartDependenciesNodeVisitor().process(deck).values()
        for dependency in part
    }


def affected_decks(git_dir: Path, paths: Iterable[Path]) -> list["DeckSettings"]:
    """Every deck of the repository a change to `paths` reaches.

    Args:
        git_dir: The repository's root.
        paths: Changed files, absolute or relative to `git_dir`.

    Returns:
        The decks' settings, in directory order.
    """
    from ..utils import all_deck_settings

    targets = {_french(git_dir / path).resolve() for path in paths}
    if not targets:
        return []
    affected = []
    for settings in all_deck_settings(git_dir):
        deck_dir = settings.paths.current_dir.resolve()
        if any(target.is_relative_to(deck_dir) for target in targets) or (
            targets & {path.resolve() for path in deck_files(settings)}
        ):
            affected.append(settings)
    return affected
