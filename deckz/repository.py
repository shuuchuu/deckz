from collections.abc import Iterator
from pathlib import Path

from yaml import safe_load

from .configuring.paths import Paths
from .deck_building import DeckBuilder
from .models.deck import Deck
from .models.definitions import SectionDefinition


def decks_iterator(git_dir: Path) -> Iterator[tuple[Path, Deck]]:
    """Iterate over all decks in the repository.

    Args:
        git_dir: Path of the repository.

    Yields:
        Accessible decks in the repository.
    """
    for targets_path in git_dir.rglob("targets.yml"):
        paths = Paths.from_defaults(targets_path.parent)
        yield (
            targets_path.parent.relative_to(git_dir),
            DeckBuilder(paths.local_latex_dir, paths.shared_latex_dir).from_targets(
                paths.deck_config, targets_path
            ),
        )


def shared_sections_iterator(
    shared_latex_dir: Path,
) -> Iterator[tuple[Path, SectionDefinition]]:
    """Iterate over all shared sections.

    Args:
        shared_latex_dir: Root repository to search.

    Yields:
        Section path (relative to the shared latex directory) and definition.
    """
    for path in shared_latex_dir.rglob("*.yml"):
        content = safe_load(path.read_text(encoding="utf8"))
        yield (
            path.parent.relative_to(shared_latex_dir),
            SectionDefinition.model_validate(content),
        )
