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

A file counts by its bytes, as in `deckz.stamps` and for the same reasons. Its
digest, and what a record holds, stay in memory for as long as the file's time
and size don't change, so that a `--watch` rebuild costs one `stat` per fragment
and per input, unless a file was written too recently for its time to tell a
further edit (`_SETTLED_NS`).
"""

from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from json import dumps, loads
from os import fspath, stat
from os.path import normpath, relpath
from pathlib import Path
from time import time_ns

from .stamps import digest
from .utils import write_atomic

type Inputs = dict[Path, str | None]
"""Each file a render read, with its `file_digest`."""

# Per thread: fragments of several outputs render at once, in the deck builder's.
_recording: ContextVar[Inputs | None] = ContextVar("render_inputs", default=None)
# By plain strings: building `Path`s took longer than the `stat`s they're for, on a
# `--watch` rebuild.
_digests: dict[str, tuple[tuple[int, int], str]] = {}
_records: dict[str, tuple[tuple[int, int], list[tuple[str, str | None]]]] = {}
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


def depends_on(*paths: Path) -> None:
    """Declare that the fragment being rendered reads `paths`, existing or not.

    Part of deckz's API for a repository's Jinja environment: see the module's \
    documentation. Does nothing outside a render.
    """
    inputs = _recording.get()
    if inputs is None:
        return
    for path in paths:
        absolute = path.absolute()
        if absolute not in inputs:
            inputs[absolute] = file_digest(absolute)


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


def write_record(record: Path, inputs: Mapping[Path, str | None]) -> None:
    """Write `inputs` to the file `record`.

    Paths are kept relative to `record`: a build directory copied along with \
    its checkout still names that checkout's files.
    """
    relative = {relpath(path, record.parent): value for path, value in inputs.items()}
    write_atomic(record, dumps(relative, sort_keys=True).encode("utf8"))


def _read_record(name: str) -> list[tuple[str, str | None]]:
    record = Path(name)
    recorded = loads(record.read_text(encoding="utf8"))
    if not isinstance(recorded, dict):
        msg = f"{name} isn't a record of render inputs"
        raise ValueError(msg)
    return [(normpath(record.parent / path), value) for path, value in recorded.items()]


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
    return any(file_digest(path) != value for path, value in inputs)
