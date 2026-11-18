import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from pytest import MonkeyPatch

from deckz import processes
from deckz.processes import MemoryWatch, kill_tree, process_tree, tree_memory

# A parent starting a child in a session of its own (as a Jupyter kernel is),
# the child holding 300 MB.
_TREE = """
import subprocess, sys, time
subprocess.Popen(
    [sys.executable, "-c", "import time; x = b'x' * 300 * 2**20; time.sleep(60)"],
    start_new_session=True,
)
time.sleep(60)
"""


def _wait_for(condition: Callable[[], bool], seconds: float = 10) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return False


def test_the_tree_s_memory_counts_a_child_in_its_own_session() -> None:
    parent = subprocess.Popen([sys.executable, "-c", _TREE])
    try:
        assert _wait_for(lambda: (tree_memory(parent.pid) or 0) > 300 * 2**20)
        watch = MemoryWatch(parent.pid, 200 * 2**20)
        assert watch.over()
        assert watch.peak > 300 * 2**20
    finally:
        members = process_tree(parent.pid)
        kill_tree(parent.pid)
        parent.wait()
    assert len(members) == 2
    assert _wait_for(lambda: not Path(f"/proc/{members[1]}").exists())


def test_a_watch_without_a_limit_never_stops() -> None:
    assert not MemoryWatch(1, None).over()


def test_tmpdir_chooses_the_scratch_directory(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", "/somewhere")
    monkeypatch.setattr(processes, "_tmp_in_memory", lambda: True)

    assert processes.scratch_parent() is None


def test_a_tmp_in_memory_sends_scratch_files_to_var_tmp(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.setattr(processes, "_tmp_in_memory", lambda: True)

    assert processes.scratch_parent() == "/var/tmp"

    monkeypatch.setattr(processes, "_tmp_in_memory", lambda: False)

    assert processes.scratch_parent() is None
