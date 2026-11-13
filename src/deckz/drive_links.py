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
(`adoptions` checks the request, `Uploader.adopt` gets deckz access to it).
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
# one.
"""


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
    by_name = {
        name: pdf
        for pdf in pdfs
        for name in (
            str(PurePosixPath(pdf.relative_to(paths.current_dir))),
            str(PurePosixPath(pdf.relative_to(paths.git_dir))),
        )
    }
    registry = load(settings)
    adopted: dict[Path, str] = {}
    for request in requests:
        name, sep, given = request.partition("=")
        name = str(PurePosixPath(name.strip()))
        if not sep or (found := parse_file_id(given.strip())) is None:
            msg = (
                f"--link {request}: give `<pdf>=<Drive link>`, e.g. --link "
                "pdf/<deck>-handout.pdf=https://drive.google.com/file/d/<id>/view"
            )
            raise DeckzError(msg)
        if (pdf := by_name.get(name)) is None:
            msg = (
                f"--link {request}: the deck builds no {name}. "
                "`deckz upload --reserve --dry-run` lists those it reserves links "
                "for, `--lang` selects the languages"
            )
            raise DeckzError(msg)
        if (known := registry.get(pdf)) is not None and known != found:
            msg = (
                f"--link {request}: {name} has a link already ({link(known)}), "
                f"in {paths.drive_links}, which handed-out PDFs may show: it "
                "keeps it. Remove its line there first if no PDF showing it was "
                "ever handed out"
            )
            raise DeckzError(msg)
        if (other := adopted.get(pdf)) is not None and other != found:
            msg = f"--link {request}: {name} is given two links"
            raise DeckzError(msg)
        if known is None:
            adopted[pdf] = found
    taken = {file: pdf for pdf, file in registry.items()}
    for pdf, found in adopted.items():
        owner = taken.setdefault(found, pdf)
        if owner != pdf:
            msg = (
                f"--link: {owner.relative_to(paths.current_dir)} and "
                f"{pdf.relative_to(paths.current_dir)} would share one Drive file "
                f"({found}): give each PDF its own"
            )
            raise DeckzError(msg)
    return adopted


def load(settings: DeckSettings) -> dict[Path, str]:
    """The deck's registry, if it has one.

    Returns:
        Each PDF's absolute path, mapped to its Drive file ID.

    Raises:
        InvalidConfigurationError: If the registry isn't a mapping of paths \
            to IDs.
    """
    path = settings.paths.drive_links
    if not path.is_file():
        return {}
    entries = load_yaml(path) or {}
    if not isinstance(entries, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in entries.items()
    ):
        msg = f"{path} should map each PDF's path to its Drive file ID"
        raise InvalidConfigurationError(msg)
    return {settings.paths.current_dir / key: value for key, value in entries.items()}


def links(settings: DeckSettings) -> dict[Path, str]:
    """The deck's links, by the absolute path of each PDF the registry names.

    Returns:
        Each PDF's link.
    """
    return {pdf: link(file_id) for pdf, file_id in load(settings).items()}


def save(settings: DeckSettings, ids: Mapping[Path, str]) -> None:
    """Write the deck's registry, sorted by path.

    Args:
        settings: The deck's settings.
        ids: Each PDF's absolute path, mapped to its Drive file ID.
    """
    import yaml

    current_dir = settings.paths.current_dir
    entries = {
        str(PurePosixPath(pdf.relative_to(current_dir))): file_id
        for pdf, file_id in ids.items()
    }
    text = _HEADER + yaml.safe_dump(dict(sorted(entries.items())), sort_keys=False)
    settings.paths.drive_links.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(settings.paths.drive_links, text.encode("utf8"))
