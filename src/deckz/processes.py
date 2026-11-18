"""Watch a child process's memory, and keep its scratch files off memory.

deckz runs code it didn't write (a lab notebook, a course notes chapter) in
child processes, which start their own (a Jupyter kernel, Spark's JVM). A run
that fills the machine gets the kernel's OOM killer to stop whichever process
it picks, the user's browser as well as the run; a cap set from outside
(`systemd-run -p MemoryMax=`) stops it with no message, and the desktop
reports each such stop. `MemoryWatch` measures the run's whole process tree
instead, so that deckz stops it itself, past a limit the repository sets, and
says which.

Linux only (`/proc`): elsewhere nothing is measured, and no run is stopped.
"""

import os
import signal
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

POLL_SECONDS = 0.5
"""How often a watched run's memory is measured."""

_PROC = Path("/proc")
_PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


def _children() -> dict[int, list[int]]:
    # Each running process's children, from `/proc/<pid>/stat`'s parent field.
    children: dict[int, list[int]] = {}
    for entry in _PROC.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="ascii", errors="replace")
        except OSError:
            continue
        # `pid (comm) state ppid ...`: `comm` may hold spaces and parentheses.
        fields = stat.rpartition(")")[2].split()
        if len(fields) > 1 and fields[1].isdigit():
            children.setdefault(int(fields[1]), []).append(int(entry.name))
    return children


def process_tree(pid: int) -> list[int]:
    """Process `pid` and its descendants.

    Returns:
        Their ids, `pid` first; only `pid` where `/proc` is missing.
    """
    if not _PROC.is_dir():
        return [pid]
    children = _children()
    tree, queue = [], [pid]
    while queue:
        current = queue.pop()
        tree.append(current)
        queue.extend(children.get(current, ()))
    return tree


def _resident(pid: int) -> int:
    try:
        statm = (_PROC / str(pid) / "statm").read_text(encoding="ascii")
    except OSError:
        return 0
    return int(statm.split()[1]) * _PAGE


def tree_memory(pid: int) -> int | None:
    """Resident memory of process `pid` and its descendants, in bytes.

    Pages several processes share count once per process: an overestimate,
    on the side of stopping a run early.

    Returns:
        The sum, or None where `/proc` is missing.
    """
    if not _PROC.is_dir():
        return None
    return sum(_resident(member) for member in process_tree(pid))


def kill_tree(pid: int) -> None:
    """Kill process `pid` and its descendants, also those in a session of their own.

    The tree is read before any is killed: a killed parent's children would
    move to init, out of reach.
    """
    for member in process_tree(pid):
        with suppress(ProcessLookupError, PermissionError):
            os.kill(member, signal.SIGKILL)


@dataclass
class MemoryWatch:
    """The memory of a run's process tree, against a limit.

    Attributes:
        pid: The run's process.
        memory_max: The limit in bytes; None measures only.
        peak: The most the tree used at a measure, in bytes.
    """

    pid: int
    memory_max: int | None
    peak: int = field(default=0)

    def over(self) -> bool:
        """Measure the tree once.

        Returns:
            Whether it uses more than `memory_max`.
        """
        if self.memory_max is None:
            return False
        memory = tree_memory(self.pid)
        if memory is None:
            return False
        self.peak = max(self.peak, memory)
        return memory > self.memory_max


def gib(size: int) -> str:
    """A size in GiB, for a message.

    Returns:
        E.g. `2.0 GiB`.
    """
    return f"{size / 2**30:.1f} GiB"


def scratch_parent() -> str | None:
    """Where a run's scratch directory goes: not in memory when that can be helped.

    A notebook downloads models and data sets into its scratch directory (its
    `HOME`, so its caches too), and Spark writes its shuffle files there: in a
    `/tmp` mounted as tmpfs, they take the machine's memory. When `TMPDIR`
    doesn't choose, and `/tmp` is a tmpfs, `/var/tmp` (on disk by the
    Filesystem Hierarchy Standard) takes them.

    Returns:
        `/var/tmp`, or None for `tempfile`'s own choice.
    """
    if os.environ.get("TMPDIR"):
        return None
    var_tmp = Path("/var/tmp")
    if not (_tmp_in_memory() and var_tmp.is_dir() and os.access(var_tmp, os.W_OK)):
        return None
    return str(var_tmp)


def _tmp_in_memory() -> bool:
    try:
        mounts = (_PROC / "self" / "mounts").read_text(encoding="utf-8")
    except OSError:
        return False
    # The last mount on `/tmp` is the one in use.
    kinds = [
        fields[2]
        for fields in map(str.split, mounts.splitlines())
        if len(fields) > 2 and fields[1] == "/tmp"
    ]
    return bool(kinds) and kinds[-1] == "tmpfs"
