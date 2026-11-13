"""A deck's Drive links: the Google Drive file each of its PDFs is uploaded to.

A PDF can only show its own link if the link exists before it's compiled, \
so `deckz upload --reserve` creates the Drive files first, empty, and \
records their IDs in the deck's registry (`paths.drive_links`): each PDF's \
path relative to the deck directory, mapped to its file ID. The files are in \
the user's Drive, so the registry is the user's too, in their config \
directory (`drive-links/<deck path>.yml`, where they may track it), shared \
by every checkout of the repository. Builds read it and never reach Drive; \
`deckz upload` then writes each PDF to its file, whose ID, and so link, \
Drive keeps across updates. Without a registry (another user, CI), a deck's \
PDFs show no link.

A link already handed out (a PDF put on Drive by hand) can be reused instead: \
`deckz upload --reserve --link <pdf>=<link>` records that file for the PDF \
(`adoptions` checks the request, `extras.uploading.adopt` gets deckz access \
to it), and `--links <file>` (`links_file`) does so for many decks at once.

A PDF can also have aliases: other Drive files, links handed out before (an \
older name, a copy put elsewhere), which `deckz upload` keeps up to date with \
the PDF's content, so that every link handed out still shows the current \
version. The PDF shows its own link only. `--alias <pdf>=<link>` \
(`alias_requests`) and the `aliases:` section of a `--links` file \
(`aliases_file`) record them, in the registry's `aliases:` section.
"""

import re
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath

from .configuring.settings import DeckSettings
from .exceptions import DeckzError, InvalidConfigurationError
from .utils import load_yaml, write_atomic

_HEADER = """\
# The Google Drive file each PDF of a deck is uploaded to, by its path in the
# deck's directory (this file's path in deckz's drive-links/ directory): the
# PDFs show these links. Written by `deckz upload --reserve` (and its
# --link). A link may be printed in handed-out PDFs: never change or remove
# one. `aliases:` lists, for a PDF, the other Drive files (links handed out
# before) each upload updates too.
"""

_ALIASES = "aliases"


def link(file_id: str) -> str:
    """The address of a Drive file, as a PDF shows it.

    Returns:
        Its view link.
    """
    return f"https://drive.google.com/file/d/{file_id}/view"


def parse_file_id(text: str) -> str | None:
    """The ID of the Drive file `text` points to.

    Args:
        text: A Drive link (`…/file/d/<id>/…`, `…?id=<id>`), or the ID itself.

    Returns:
        The ID, or None if `text` is neither.
    """
    if match := re.search(r"/d/([\w-]+)|[?&]id=([\w-]+)", text):
        return match.group(1) or match.group(2)
    return text if re.fullmatch(r"[\w-]{10,}", text) else None


def adoptions(
    settings: DeckSettings, pdfs: Iterable[Path], requests: Iterable[str]
) -> dict[Path, str]:
    """The Drive files `deckz upload --reserve --link` asks to reuse.

    Args:
        settings: The deck's settings.
        pdfs: The PDFs links can be reserved for, absolute paths.
        requests: Each `<pdf>=<link>`, the PDF's path relative to the deck's \
            directory or to the repository (as `--reserve --dry-run` lists \
            it), the link a Drive link or a file ID.

    Returns:
        Each PDF's file ID, those the registry has already with this ID left out.

    Raises:
        DeckzError: If a request is malformed, names a PDF the deck doesn't \
            build, gives a new link to a PDF that has one already, or gives \
            one file to two PDFs.
    """
    paths = settings.paths
    by_name = _by_name(settings, pdfs)
    registry = load(settings)
    adopted: dict[Path, str] = {}
    for request in requests:
        name, sep, given = request.partition("=")
        name = str(PurePosixPath(name.strip()))
        if not sep or (found := parse_file_id(given.strip())) is None:
            msg = (
                f"{request}: give `<pdf>=<Drive link>`, e.g. --link "
                "pdf/<deck>-handout.pdf=https://drive.google.com/file/d/<id>/view"
            )
            raise DeckzError(msg)
        if (pdf := by_name.get(name)) is None:
            msg = (
                f"{request}: the deck builds no {name}. "
                "`deckz upload --reserve --dry-run` lists those it reserves links "
                "for, `--lang` selects the languages"
            )
            raise DeckzError(msg)
        if (known := registry.get(pdf)) is not None and known != found:
            msg = (
                f"{request}: {name} has a link already ({link(known)}), "
                f"in {paths.drive_links}, which handed-out PDFs may show: it "
                "keeps it. Remove its line there first if no PDF showing it was "
                "ever handed out"
            )
            raise DeckzError(msg)
        if (other := adopted.get(pdf)) is not None and other != found:
            msg = f"{request}: {name} is given two links"
            raise DeckzError(msg)
        if known is None:
            adopted[pdf] = found
    taken = {file: pdf for pdf, file in registry.items()}
    for pdf, found in adopted.items():
        owner = taken.setdefault(found, pdf)
        if owner != pdf:
            msg = (
                f"{owner.relative_to(paths.current_dir)} and "
                f"{pdf.relative_to(paths.current_dir)} would share one Drive file "
                f"({found}): give each PDF its own"
            )
            raise DeckzError(msg)
    return adopted


def alias_requests(
    settings: DeckSettings,
    pdfs: Iterable[Path],
    requests: Iterable[str],
    reserved: Mapping[Path, str],
) -> dict[Path, list[str]]:
    """The Drive files `deckz upload --reserve --alias` asks to keep up to date.

    Args:
        settings: The deck's settings.
        pdfs: The PDFs links can be reserved for, absolute paths.
        requests: Each `<pdf>=<link>`, as `adoptions` takes them.
        reserved: Each PDF's own file ID: the registry's, and those this \
            run adopts.

    Returns:
        Each PDF's new aliases, those the registry has already left out.

    Raises:
        DeckzError: If a request is malformed, names a PDF the deck doesn't \
            build, or a file that is a PDF's own or another PDF's alias.
    """
    paths = settings.paths
    by_name = _by_name(settings, pdfs)
    known = load_aliases(settings)
    owners = {file_id: pdf for pdf, ids in known.items() for file_id in ids}
    own = {file_id: pdf for pdf, file_id in reserved.items()}
    added: dict[Path, list[str]] = {}
    for request in requests:
        name, sep, given = request.partition("=")
        name = str(PurePosixPath(name.strip()))
        if not sep or (found := parse_file_id(given.strip())) is None:
            msg = (
                f"{request}: give `<pdf>=<Drive link>`, e.g. --alias "
                "pdf/<deck>-handout.pdf=https://drive.google.com/file/d/<id>/view"
            )
            raise DeckzError(msg)
        if (pdf := by_name.get(name)) is None:
            msg = (
                f"{request}: the deck builds no {name}. "
                "`deckz upload --reserve --dry-run` lists those it reserves links "
                "for, `--lang` selects the languages"
            )
            raise DeckzError(msg)
        if (owner := own.get(found)) is not None:
            msg = (
                f"{request}: {found} is the Drive file of "
                f"{owner.relative_to(paths.current_dir)} itself, not an alias"
            )
            raise DeckzError(msg)
        if (owner := owners.setdefault(found, pdf)) != pdf:
            msg = (
                f"{request}: {found} is an alias of "
                f"{owner.relative_to(paths.current_dir)} already: a Drive file "
                "follows one PDF"
            )
            raise DeckzError(msg)
        if found not in known.get(pdf, []) and found not in added.get(pdf, []):
            added.setdefault(pdf, []).append(found)
    return added


def _by_name(settings: DeckSettings, pdfs: Iterable[Path]) -> dict[str, Path]:
    # Each PDF by its path in the deck's directory and in the repository.
    paths = settings.paths
    return {
        name: pdf
        for pdf in pdfs
        for name in (
            str(PurePosixPath(pdf.relative_to(paths.current_dir))),
            str(PurePosixPath(pdf.relative_to(paths.git_dir))),
        )
    }


def links_file(path: Path, git_dir: Path) -> dict[Path, list[str]]:
    """The requests of a `deckz upload --reserve --links` file, by deck.

    The file maps each PDF's path in the repository to its Drive link \
    (`decks/x/pdf/x-handout.pdf: https://drive.google.com/file/d/<id>/view`). \
    A PDF's deck is the closest directory above it with a `deck.yml`. Its \
    `aliases:` section is `aliases_file`'s.

    Args:
        path: The file.
        git_dir: The repository's root.

    Returns:
        Each deck's directory, mapped to its `<pdf>=<link>` requests (as \
        `adoptions` takes them).

    Raises:
        DeckzError: If the file isn't a mapping of paths to links, a path is \
            in no deck, or two PDFs are given the same file.
    """
    entries = _links_entries(path)
    others = {key: value for key, value in entries.items() if key != _ALIASES}
    links = {key: value for key, value in others.items() if isinstance(value, str)}
    if len(links) != len(others):
        msg = (
            f"--links {path}: it should map each PDF's path in the repository to "
            "its Drive link, e.g. `decks/x/pdf/x-handout.pdf: "
            "https://drive.google.com/file/d/<id>/view`"
        )
        raise DeckzError(msg)
    by_deck: dict[Path, list[str]] = {}
    given: dict[str, str] = {}
    for name, value in links.items():
        deck = _deck_of(path, name, git_dir)
        file_id = parse_file_id(value.strip())
        if file_id is not None and (other := given.setdefault(file_id, name)) != name:
            msg = (
                f"--links {path}: {other} and {name} would share one Drive file "
                f"({file_id}): give each PDF its own"
            )
            raise DeckzError(msg)
        by_deck.setdefault(deck, []).append(f"{name}={value}")
    return by_deck


def aliases_file(path: Path, git_dir: Path) -> dict[Path, list[str]]:
    """The alias requests of a `deckz upload --reserve --links` file, by deck.

    Its `aliases:` section maps PDFs' paths in the repository to the Drive \
    links handed out before, one or a list, that uploads keep up to date:

        aliases:
          decks/x/pdf/x-handout.pdf:
            - https://drive.google.com/file/d/<id>/view

    Args:
        path: The file.
        git_dir: The repository's root.

    Returns:
        Each deck's directory, mapped to its `<pdf>=<link>` requests (as \
        `alias_requests` takes them).

    Raises:
        DeckzError: If the section isn't a mapping of paths to links, or a \
            path is in no deck.
    """
    section = _links_entries(path).get(_ALIASES) or {}
    if not isinstance(section, dict) or not all(
        isinstance(key, str)
        and (
            isinstance(value, str)
            or (isinstance(value, list) and all(isinstance(v, str) for v in value))
        )
        for key, value in section.items()
    ):
        msg = (
            f"--links {path}: its `aliases:` section should map each PDF's path "
            "in the repository to a Drive link, or a list of them"
        )
        raise DeckzError(msg)
    by_deck: dict[Path, list[str]] = {}
    for name, value in section.items():
        deck = _deck_of(path, name, git_dir)
        for given in [value] if isinstance(value, str) else value:
            by_deck.setdefault(deck, []).append(f"{name}={given}")
    return by_deck


def _links_entries(path: Path) -> dict[str, object]:
    if not path.is_file():
        msg = f"--links {path}: no such file"
        raise DeckzError(msg)
    entries = load_yaml(path) or {}
    if not isinstance(entries, dict) or not all(
        isinstance(key, str) for key in entries
    ):
        msg = (
            f"--links {path}: it should map each PDF's path in the repository to "
            "its Drive link, e.g. `decks/x/pdf/x-handout.pdf: "
            "https://drive.google.com/file/d/<id>/view`"
        )
        raise DeckzError(msg)
    return entries


def _deck_of(path: Path, name: str, git_dir: Path) -> Path:
    pdf = git_dir / name
    deck = next(
        (
            parent
            for parent in pdf.parents
            if parent.is_relative_to(git_dir) and (parent / "deck.yml").is_file()
        ),
        None,
    )
    if deck is None:
        msg = (
            f"--links {path}: {name} is in no deck (no deck.yml above it): give "
            "its path from the repository's root"
        )
        raise DeckzError(msg)
    return deck


def load(settings: DeckSettings) -> dict[Path, str]:
    """The deck's registry, if it has one, its aliases apart.

    A registry that isn't a mapping of paths to IDs (`aliases:` apart) \
    raises an `InvalidConfigurationError`.

    Returns:
        Each PDF's absolute path, mapped to its Drive file ID.
    """
    entries = _registry(settings)
    return {
        settings.paths.current_dir / key: value
        for key, value in entries.items()
        if key != _ALIASES and isinstance(value, str)
    }


def load_aliases(settings: DeckSettings) -> dict[Path, list[str]]:
    """The aliases of the deck's PDFs, its registry's `aliases:` section.

    Returns:
        Each PDF's absolute path, mapped to the IDs of the other Drive files \
        its uploads update.

    Raises:
        InvalidConfigurationError: If the section isn't a mapping of paths \
            to lists of IDs.
    """
    section = _registry(settings).get(_ALIASES) or {}
    if not isinstance(section, dict) or not all(
        isinstance(key, str)
        and isinstance(value, list)
        and all(isinstance(v, str) for v in value)
        for key, value in section.items()
    ):
        msg = (
            f"{settings.paths.drive_links}: its `aliases:` section should map "
            "each PDF's path to a list of Drive file IDs"
        )
        raise InvalidConfigurationError(msg)
    return {
        settings.paths.current_dir / key: list(value) for key, value in section.items()
    }


def _registry(settings: DeckSettings) -> dict[str, object]:
    path = settings.paths.drive_links
    if not path.is_file():
        return {}
    entries = load_yaml(path) or {}
    if not isinstance(entries, dict) or not all(
        isinstance(key, str) and (key == _ALIASES or isinstance(value, str))
        for key, value in entries.items()
    ):
        msg = f"{path} should map each PDF's path to its Drive file ID"
        raise InvalidConfigurationError(msg)
    return entries


def links(settings: DeckSettings) -> dict[Path, str]:
    """The deck's links, by the absolute path of each PDF the registry names.

    Returns:
        Each PDF's link.
    """
    return {pdf: link(file_id) for pdf, file_id in load(settings).items()}


def save(
    settings: DeckSettings,
    ids: Mapping[Path, str],
    aliases: Mapping[Path, Iterable[str]] | None = None,
) -> None:
    """Write the deck's registry, sorted by path.

    Args:
        settings: The deck's settings.
        ids: Each PDF's absolute path, mapped to its Drive file ID.
        aliases: Each PDF's aliases (`load_aliases`); None keeps the \
            registry's.
    """
    import yaml

    if aliases is None:
        aliases = load_aliases(settings)
    current_dir = settings.paths.current_dir

    def key(pdf: Path) -> str:
        return str(PurePosixPath(pdf.relative_to(current_dir)))

    entries: dict[str, object] = dict(
        sorted((key(pdf), file_id) for pdf, file_id in ids.items())
    )
    if section := {key(pdf): list(found) for pdf, found in aliases.items() if found}:
        entries[_ALIASES] = dict(sorted(section.items()))
    text = _HEADER + yaml.safe_dump(entries, sort_keys=False)
    settings.paths.drive_links.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(settings.paths.drive_links, text.encode("utf8"))
