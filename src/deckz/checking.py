"""Assemble synthetic decks for the `deckz run shared`/`deckz run all` commands.

Both commands validate shared content without needing a full repository \
compile, by building one throwaway [`Deck`][deckz.models.Deck] in memory \
(never written to disk as yaml) containing every shared section expanded \
to a synthetic "all files" flavor -- see \
[`Parser.all_files_section`][deckz.components.parser.Parser.all_files_section].

Each section is its own part, so each compiles to its own PDF: one document \
holding the whole repository's content would need more memory than a \
typical machine has (Typst takes a few MB per page), and a compilation that \
stops at its first error would hide every later section's errors.
"""

from collections.abc import Iterable
from pathlib import Path, PurePath

from .components.factory import DeckSettingsFactory
from .components.parser import Parser
from .models import Deck, Lang, Node, Part, PartName, UnresolvedPath
from .utils import all_deck_settings, shared_section_ids


def _part_name(section_id: str) -> PartName:
    return PartName(section_id.replace("/", "-"))


def check_scratch_dir(git_dir: Path, name: str) -> Path:
    """Directory used as the synthetic `deckz check variables` deck's `current_dir`.

    Created eagerly: `DeckSettings.from_yaml` resolves `git_dir` via \
    `pygit2.discover_repository`, which fails on a path that doesn't exist \
    yet, and the directory is meant to persist across runs anyway (so \
    fragment caching and manual PDF inspection both work).

    Args:
        git_dir: Root of the deckz-managed repository.
        name: Distinguishes the scratch tree from any other under `.check`.

    Returns:
        The (now existing) scratch directory.
    """
    path = git_dir / ".check" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_scratch_dir(git_dir: Path, name: str) -> Path:
    """Directory used as the `deckz run shared`/`deckz run all` deck's `current_dir`.

    Created eagerly: `DeckSettings.from_yaml` resolves `git_dir` via \
    `pygit2.discover_repository`, which fails on a path that doesn't exist \
    yet, and the directory is meant to persist across runs anyway (so \
    fragment caching and manual PDF inspection both work).

    Args:
        git_dir: Root of the deckz-managed repository.
        name: Distinguishes the `run shared`/`run all` scratch trees.

    Returns:
        The (now existing) scratch directory.
    """
    path = git_dir / ".run" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_shared_deck(
    latex_dir: Path,
    file_extensions: Iterable[str],
    lang: Lang,
    *,
    name: str = "shared",
) -> Deck:
    """Build a deck containing every shared section, expanded to all its files.

    Args:
        latex_dir: Path to the shared latex directory.
        file_extensions: Extensions to try, in order, when resolving files.
        lang: Language to build the deck in.
        name: Name given to the built deck.

    Returns:
        The built deck.
    """
    parser = Parser(
        local_latex_dir=latex_dir,
        shared_latex_dir=latex_dir,
        file_extensions=file_extensions,
        lang=lang,
    )
    deck = Deck(
        name=name,
        parts={
            _part_name(section_id): Part(
                title=None, nodes=[parser.all_files_section(section_id)]
            )
            for section_id in shared_section_ids(latex_dir)
        },
    )
    parser.validate(deck)
    return deck


def build_all_deck(
    git_dir: Path,
    latex_dir: Path,
    file_extensions: Iterable[str],
    lang: Lang,
) -> Deck:
    """Build `build_shared_deck`'s deck, plus every deck-local override.

    For every real deck that locally overrides at least one file of a \
    shared section, adds one extra copy of that section using the deck's \
    own file(s) in place of the shared one(s).

    Args:
        git_dir: Root of the deckz-managed repository.
        latex_dir: Path to the shared latex directory.
        file_extensions: Extensions to try, in order, when resolving files.
        lang: Language to build the deck in.

    Returns:
        The built deck.
    """
    deck = build_shared_deck(latex_dir, file_extensions, lang, name="run-all")
    plain_sections: dict[str, Node] = {
        part.nodes[0].unresolved_path.as_posix(): part.nodes[0]
        for part in deck.parts.values()
    }
    deck_settings = sorted(
        all_deck_settings(git_dir), key=lambda s: s.paths.current_dir.as_posix()
    )
    for section_id, plain_section in plain_sections.items():
        if plain_section.parsing_error is not None:
            continue
        counter = 2
        for settings in deck_settings:
            parser = DeckSettingsFactory(settings, lang=lang).parser()
            candidate = parser.all_files_section(section_id)
            overridden = any(
                node.parsing_error is None
                and not node.resolved_path.is_relative_to(latex_dir)
                for node in candidate.nodes
            )
            if not overridden:
                continue
            deck_label = settings.paths.current_dir.relative_to(git_dir).as_posix()
            candidate.unresolved_path = UnresolvedPath(
                PurePath(f"{section_id}-{counter}")
            )
            candidate.title = f"{candidate.title or section_id} [{deck_label}]"
            deck.parts[_part_name(f"{section_id}-{counter}")] = Part(
                title=None, nodes=[candidate]
            )
            counter += 1
    return deck
