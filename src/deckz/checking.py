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

from pathlib import Path, PurePath

from .components.factory import DeckSettingsFactory, GlobalSettingsFactory
from .configuring.settings import DeckSettings, GlobalSettings
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


def preview_settings(settings: DeckSettings, *parts: str) -> DeckSettings:
    """Copy of a deck's settings writing to a `deckz run file`/`section` scratch tree.

    The deck itself (its `current_dir`, local content dir, variables) stays \
    the same: only the build and PDF directories move, under \
    `<git_dir>/.run/<parts...>/`, so repeated previews don't clutter the \
    deck's own output.

    Args:
        settings: Settings of the deck the preview is run from.
        parts: Path components of the scratch tree under `.run`, e.g. \
            `("file", "about")`.

    Returns:
        The copy. `settings` is left untouched.
    """
    scratch_dir = settings.paths.git_dir.joinpath(".run", *parts)
    return settings.with_output_dirs(scratch_dir / ".build", scratch_dir / "pdf")


def build_shared_deck(
    settings: GlobalSettings,
    lang: Lang,
    *,
    name: str = "shared",
) -> Deck:
    """Build a deck containing every shared section, expanded to all its files.

    Args:
        settings: Settings of the repository.
        lang: Language to build the deck in.
        name: Name given to the built deck.

    Returns:
        The built deck.
    """
    parser = GlobalSettingsFactory(settings).shared_parser(lang)
    content_dir = settings.paths.content_dir
    deck = Deck(
        name=name,
        parts={
            _part_name(section_id): Part(
                title=None, nodes=[parser.all_files_section(section_id)]
            )
            for section_id in shared_section_ids(content_dir)
        },
    )
    parser.validate(deck)
    return deck


def build_all_deck(settings: GlobalSettings, lang: Lang) -> Deck:
    """Build `build_shared_deck`'s deck, plus every deck-local override.

    For every real deck that locally overrides at least one file of a \
    shared section, adds one extra copy of that section using the deck's \
    own file(s) in place of the shared one(s).

    Args:
        settings: Settings of the repository.
        lang: Language to build the deck in.

    Returns:
        The built deck.
    """
    git_dir = settings.paths.git_dir
    content_dir = settings.paths.content_dir
    deck = build_shared_deck(settings, lang, name="run-all")
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
        for local_settings in deck_settings:
            parser = DeckSettingsFactory(local_settings, lang=lang).parser()
            candidate = parser.all_files_section(section_id)
            overridden = any(
                node.parsing_error is None
                and not node.resolved_path.is_relative_to(content_dir)
                for node in candidate.nodes
            )
            if not overridden:
                continue
            label = local_settings.paths.current_dir.relative_to(git_dir).as_posix()
            candidate.unresolved_path = UnresolvedPath(
                PurePath(f"{section_id}-{counter}")
            )
            candidate.title = f"{candidate.title or section_id} [{label}]"
            deck.parts[_part_name(f"{section_id}-{counter}")] = Part(
                title=None, nodes=[candidate]
            )
            counter += 1
    return deck
