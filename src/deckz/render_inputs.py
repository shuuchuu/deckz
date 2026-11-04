"""What a content fragment's rendering read, besides its own source.

A fragment's build copy matching its source doesn't make its output current: a
filter of the repository's Jinja environment may have read a notebook's
metadata, or an asset's credits, and these change on their own. deckz can't
guess those reads, so the code doing one declares it, right before reading:

```python
from deckz.render_inputs import depends_on

def needs_gpu(notebook: Path) -> bool:
    depends_on(notebook)
    return "gpuType" in json.loads(notebook.read_text())["metadata"]
```

Before the read, so that an edit racing the render is seen by the next build,
and also for a file that doesn't exist: a fallback ends once it appears. Outside
a render, `depends_on` does nothing, so such a function serves scripts too. A
memoized function declares nothing the second time it's called: the declaration
goes in the caller, or in the function the memoized one's result is read through.

The deck builder renders each fragment within `recording`, and records what was
declared next to the build copy (`write_record`). The next build renders the
fragment again when one of those files changed (`inputs_changed`).

A file counts by its bytes, as in `deckz.stamps` and for the same reasons, unless
the code reading it says it reads less: `depends_on_json` for one value of a JSON
file, `depends_on_presence` for whether the file exists. A notebook's outputs
written back then leave alone the fragments that only read its metadata. The part
is declared as data, not as a function: a later build checks a record without the
code that wrote it having run.

A digest, and what a record holds, stay in memory for as long as the file's time
and size don't change, so that a `--watch` rebuild costs one `stat` per fragment
and per input, unless a file was written too recently for its time to tell a
further edit (`_SETTLED_NS`).
"""

from collections import defaultdict
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from json import dumps, loads
from os import fspath, stat
from os.path import isfile, normpath, relpath
from pathlib import Path
from time import time_ns

from .stamps import digest
from .utils import write_atomic

type Input = Path | tuple[Path, str]
"""A file a render read: all of it, or the part of it a `str` describes."""
type Inputs = dict[Input, str | None]
"""Each input a render read, with its digest."""

# Per thread: fragments of several outputs render at once, in the deck builder's.
_recording: ContextVar[Inputs | None] = ContextVar("render_inputs", default=None)
# By plain strings: building `Path`s took longer than the `stat`s they're for, on a
# `--watch` rebuild.
_digests: dict[str, tuple[tuple[int, int], str]] = {}
_json_digests: defaultdict[str, dict[str, tuple[tuple[int, int], str]]] = defaultdict(
    dict
)
_records: dict[str, tuple[tuple[int, int], list[tuple[str, str | None]]]] = {}
_PRESENCE = "presence"
"""The part of a file `depends_on_presence` declares; any other is JSON keys."""
_PART_SEPARATOR = "\0"
"""Between a path and its part in a record: no path holds it."""
_SETTLED_NS = 2_000_000_000
"""A file written less than this ago isn't kept in memory: an edit of the same \
size would leave its time as it is, a time being a few milliseconds coarse here \
and up to two seconds on other filesystems (git's "racily clean" entries). A \
record rewritten usually has the same size: digests do."""


def _settled[T](
    memo: dict[str, tuple[tuple[int, int], T]], name: str, read: Callable[[str], T]
) -> T:
    # `read(name)`, or what it gave while `name`'s time and size stay the same.
    status = stat(name)  # ruff: ignore[os-stat] (see `_digests`)
    signature = (status.st_mtime_ns, status.st_size)
    known = memo.get(name)
    if known is not None and known[0] == signature:
        return known[1]
    value = read(name)
    if time_ns() - status.st_mtime_ns > _SETTLED_NS:
        memo[name] = (signature, value)
    return value


def _read_digest(name: str) -> str:
    return digest([Path(name)])


def file_digest(path: Path | str) -> str | None:
    """The digest of `path`'s bytes, read again only if its time or size changed.

    Memoized for this process, unless `path` was written just now.

    Returns:
        The digest, or None if there's no such file (a directory isn't one).
    """
    try:
        return _settled(_digests, fspath(path), _read_digest)
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return None


def _read_json_digest(name: str, part: str) -> str:
    # A file that isn't JSON counts by its bytes: an edit of it is still seen.
    try:
        value = loads(Path(name).read_text(encoding="utf8"))
    except ValueError:
        return digest([Path(name)])
    for key in loads(part):
        value = value.get(key) if isinstance(value, dict) else None
    return sha256(dumps(value, sort_keys=True).encode("utf8")).hexdigest()


def part_digest(path: Path | str, part: str) -> str | None:
    """The digest of `part` of `path`, as `file_digest` gives its bytes'.

    Returns:
        The digest, or None if there's no such file (a directory isn't one).
    """
    name = fspath(path)
    if part == _PRESENCE:
        # ruff: ignore[os-path-isfile] (see `_digests`)
        return _PRESENCE if isfile(name) else None
    try:
        return _settled(
            _json_digests[part], name, lambda name: _read_json_digest(name, part)
        )
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return None


def _declare(path: Path, part: str | None) -> None:
    inputs = _recording.get()
    if inputs is None:
        return
    absolute = path.absolute()
    declared = absolute if part is None else (absolute, part)
    if declared not in inputs:
        inputs[declared] = (
            file_digest(absolute) if part is None else part_digest(absolute, part)
        )


def depends_on(*paths: Path) -> None:
    """Declare that the fragment being rendered reads `paths`, existing or not.

    Part of deckz's API for a repository's Jinja environment: see the module's \
    documentation. Does nothing outside a render.
    """
    for path in paths:
        _declare(path, None)


def depends_on_json(path: Path, *keys: str) -> None:
    """Declare that the fragment being rendered reads one value of a JSON file.

    Like `depends_on`, for the value at `keys` only: the rest of `path` can change \
    without the fragment being rendered again. A key missing counts as a null \
    value, and a file that isn't JSON by its bytes.
    """
    _declare(path, dumps(keys))


def depends_on_presence(*paths: Path) -> None:
    """Declare that the fragment being rendered reads whether `paths` exist.

    Like `depends_on`, for their existence only: their content can change without \
    the fragment being rendered again.
    """
    for path in paths:
        _declare(path, _PRESENCE)


@contextmanager
def recording() -> Generator[Inputs]:
    """Gather what `depends_on` declares meanwhile, in this thread.

    Yields:
        The files declared so far.
    """
    inputs: Inputs = {}
    token = _recording.set(inputs)
    try:
        yield inputs
    finally:
        _recording.reset(token)


def write_record(record: Path, inputs: Mapping[Input, str | None]) -> None:
    """Write `inputs` to the file `record`.

    Paths are kept relative to `record`: a build directory copied along with \
    its checkout still names that checkout's files.
    """

    def key(declared: Input) -> str:
        if isinstance(declared, Path):
            return relpath(declared, record.parent)
        path, part = declared
        return f"{relpath(path, record.parent)}{_PART_SEPARATOR}{part}"

    relative = {key(declared): value for declared, value in inputs.items()}
    write_atomic(record, dumps(relative, sort_keys=True).encode("utf8"))


def _read_record(name: str) -> list[tuple[str, str | None]]:
    record = Path(name)
    recorded = loads(record.read_text(encoding="utf8"))
    if not isinstance(recorded, dict):
        msg = f"{name} isn't a record of render inputs"
        raise ValueError(msg)
    entries = []
    for key, value in recorded.items():
        path, separator, part = key.partition(_PART_SEPARATOR)
        entries.append((normpath(record.parent / path) + separator + part, value))
    return entries


def _current_digest(entry: str) -> str | None:
    path, separator, part = entry.partition(_PART_SEPARATOR)
    return part_digest(path, part) if separator else file_digest(path)


def inputs_changed(record: Path) -> bool:
    """Whether a file of `record` changed, appeared or went away since it was written.

    Returns:
        True as well if `record` is missing or unreadable: nothing tells what \
        the render read, and a fragment rendered with no input has a record.
    """
    try:
        inputs = _settled(_records, fspath(record), _read_record)
    except (OSError, ValueError):
        return True
    return any(_current_digest(entry) != value for entry, value in inputs)
