"""The source files a person edits in a workspace, from studioz's editor.

Only the repository's material: content and deck files (`EDITABLE`), never
a hidden directory's (`.git`, builds), and a save never overwrites what
changed on disk since the editor read it (another editor, the agent): each
read gives the file's version, and a save names the version it replaces.
"""

from hashlib import sha256
from pathlib import Path
from shutil import copymode
from tempfile import NamedTemporaryFile

EDITABLE = frozenset({".md", ".yml"})


class ChangedOnDiskError(Exception):
    """The file isn't the version the save replaces anymore."""

    def __init__(self, version: str) -> None:
        super().__init__(version)
        self.version = version
        """The file's version now."""


def source(workspace: Path, file: str) -> Path | None:
    """The workspace's file `file`, if it's one studioz edits.

    Returns:
        Its path, None unless `file` is a relative path within the \
        workspace, through no hidden directory, to an existing file whose \
        suffix is `EDITABLE`.
    """
    relative = Path(file)
    parts = relative.parts
    if not parts or relative.is_absolute() or any(p.startswith(".") for p in parts):
        return None
    path = workspace / relative
    if path.suffix not in EDITABLE or not path.is_file():
        return None
    if not path.resolve().is_relative_to(workspace.resolve()):
        return None
    return path


def _version(data: bytes) -> str:
    return sha256(data).hexdigest()[:16]


def read(path: Path) -> tuple[str, str]:
    """The file's text and version.

    Returns:
        Its text and the version a save of it names.
    """
    data = path.read_bytes()
    return data.decode("utf8"), _version(data)


def save(path: Path, text: str, version: str) -> str:
    """Replace the file's `version` with `text`.

    Written to a temporary file then moved, so that the watch never builds
    half a file.

    Returns:
        The new version.

    Raises:
        ChangedOnDiskError: If the file isn't `version` anymore.
    """
    on_disk = path.read_bytes()
    current = _version(on_disk)
    if current != version:
        raise ChangedOnDiskError(current)
    # The file keeps its line endings: a browser posts a form's text with
    # CRLF ones, whatever the file had (and the editor only knows LF).
    text = text.replace("\r\n", "\n")
    if b"\r\n" in on_disk:
        text = text.replace("\n", "\r\n")
    data = text.encode("utf8")
    with NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as temporary:
        temporary.write(data)
    copymode(path, temporary.name)
    Path(temporary.name).replace(path)
    return _version(data)
