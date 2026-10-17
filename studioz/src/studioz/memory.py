"""The machine's memory: shown in the status bar, and what holds new jobs back.

Memory, not CPU, bounds what the machine does at once (plan, "Finding 4"): a
large deck's compilation takes about 2 GB, up to deckz's `typst_memory_max`,
a scene's render as much, and each workspace's watch and agent keep theirs.
deckz bounds its compilations machine-wide; studioz also holds a job back
while less than its threshold is available (`studioz.jobs`), so that a build
started in one workspace doesn't push the machine into swap while others
run. Linux only (`/proc/meminfo`, as deckz's `typst_memory_max`): elsewhere
nothing is shown nor held.
"""

from dataclasses import dataclass
from pathlib import Path

GIB = 1 << 30

DEFAULT_MIN_FREE = 3 * GIB
"""A large compilation's 2 GB, and some room: studioz's `--min-free-memory`."""

_MEMINFO = Path("/proc/meminfo")


@dataclass(frozen=True)
class Memory:
    total: int
    """Bytes."""
    available: int
    """Bytes the kernel can give without swapping (`MemAvailable`)."""


def read(meminfo: Path = _MEMINFO) -> Memory | None:
    """The machine's memory now.

    Returns:
        Its total and what's available, None where Linux's `/proc` isn't.
    """
    try:
        lines = meminfo.read_text(encoding="ascii").splitlines()
    except OSError:
        return None
    found = {}
    for line in lines:
        name, _, value = line.partition(":")
        if name in {"MemTotal", "MemAvailable"}:
            found[name] = int(value.split()[0]) * 1024  # In kB.
    if len(found) < 2:
        return None
    return Memory(found["MemTotal"], found["MemAvailable"])


def gib(size: int) -> str:
    """A size in GiB, as French writes it: `2,4 Go`.

    Returns:
        It.
    """
    return f"{size / GIB:.1f} Go".replace(".", ",")
