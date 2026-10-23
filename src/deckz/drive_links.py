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
"""

from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from .configuring.settings import DeckSettings
from .exceptions import InvalidConfigurationError
from .utils import load_yaml, write_atomic

_HEADER = """\
# The Google Drive file each PDF of a deck is uploaded to, by its path in the
# deck's directory (this file's path in deckz's drive-links/ directory): the
# PDFs show these links. Written by `deckz upload
# --reserve`. A link may be printed in handed-out PDFs: never change or
# remove one.
"""


def link(file_id: str) -> str:
    """The address of a Drive file, as a PDF shows it.

    Returns:
        Its view link.
    """
    return f"https://drive.google.com/file/d/{file_id}/view"


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
