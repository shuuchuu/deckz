"""Assemble synthetic decks for the `deckz check shared`/`deckz check all` commands.

Both commands validate shared content without needing a full repository \
compile, by building one throwaway [`Deck`][deckz.models.Deck] in memory \
(never written to disk as yaml) containing every shared section expanded \
to a synthetic "all files" flavor -- see \
[`Parser.all_files_section`][deckz.components.parser.Parser.all_files_section].
"""

from collections.abc import Iterable, Iterator
from pathlib import Path, PurePath

from .components.factory import DeckSettingsFactory
from .components.parser import Parser
from .models import Deck, Lang, Node, Part, PartName, UnresolvedPath
from .utils import all_deck_settings, shared_section_ids

_PART_NAME = PartName("sections")


def check_scratch_dir(git_dir: Path, name: str) -> Path:
    """Directory used as the synthetic check deck's `current_dir`.

    Created eagerly: `DeckSettings.from_yaml` resolves `git_dir` via \
    `pygit2.discover_repository`, which fails on a path that doesn't exist \
    yet, and the directory is meant to persist across runs anyway (so \
    incremental compilation and manual PDF inspection both work).

    Args:
        git_dir: Root of the deckz-managed repository.
        name: Distinguishes the `check shared`/`check all` scratch trees.

    Returns:
        The (now existing) scratch directory.
    """
    path = git_dir / ".check" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def check_scratch_dirs(git_dir: Path) -> Iterator[Path]:
    """Every existing check-command scratch directory, if any.

    These are wholly synthetic, throwaway trees (never containing a real \
    `deck.yml`), unlike a real deck's directory -- so, unlike \
    `deckz clean deck`/`deckz clean all`'s handling of real decks, removing \
    one in full (not just its build directory) is safe, and avoids stale \
    output lingering after a shared section is renamed or removed.

    Args:
        git_dir: Root of the deckz-managed repository.

    Yields:
        The existing scratch directories directly under `<git_dir>/.check`.
    """
    check_dir = git_dir / ".check"
    if not check_dir.is_dir():
        return
    yield from (path for path in sorted(check_dir.iterdir()) if path.is_dir())


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
    nodes: list[Node] = [
        parser.all_files_section(section_id)
        for section_id in shared_section_ids(latex_dir)
    ]
    deck = Deck(name=name, parts={_PART_NAME: Part(title=None, nodes=nodes)})
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
    deck = build_shared_deck(latex_dir, file_extensions, lang, name="check-all")
    part = deck.parts[_PART_NAME]
    plain_sections = {node.unresolved_path.as_posix(): node for node in part.nodes}
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
            part.nodes.append(candidate)
            counter += 1
    return deck
