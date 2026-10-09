from pathlib import Path
from typing import TYPE_CHECKING

from . import app

if TYPE_CHECKING:
    from collections.abc import Callable

    from ....labs.gpu import GpuRun, GpuStatus


@app.command()
def status(
    *,
    watch: bool = False,
    interval: int = 120,
    plain: bool = False,
    machine: str | None = None,
    workdir: Path = Path(),
) -> None:
    """Show each machine's state and each queued notebook's.

    Each time, fetches the executed notebooks, appends a report of each newly
    finished one to its machine's `notes.md` (in `labs_gpu_dir`), so an
    interrupted session loses nothing, and prints those reports; then runs
    the hooks of the finished hooked runs, and sends the notebooks held for
    them. With --watch, polls until every queued and held notebook is done.

    Args:
        watch: Keep polling, fetching and noting finished runs until the
            queues are done
        interval: Seconds between two polls under --watch
        plain: One tab-separated line per machine (`machine`, name, state)
            and per notebook (name, state, exit code, seconds), for a script
            or an agent, instead of a table
        machine: Show only this machine, instead of every one rented
        workdir: Path to move into before running the command

    """
    from time import sleep

    from ....configuring.settings import GlobalSettings
    from ....labs.gpu import GpuRun, machines

    settings = GlobalSettings.from_yaml(workdir)
    runs = [
        GpuRun(settings, machine=name)
        for name in ([machine] if machine else machines(settings))
    ]
    if not runs:
        print("machine\tnone" if plain else "No machine rented.")
        return
    # Polls in a row a machine couldn't be reached, given up on at _MAX_MISSES.
    misses = dict.fromkeys(range(len(runs)), 0)
    while True:
        busy = False
        for i, gpu_run in enumerate(runs):
            if misses[i] >= _MAX_MISSES:
                continue
            polled = _poll(gpu_run, plain=plain)
            misses[i] = misses[i] + 1 if polled is None else 0
            if misses[i] == _MAX_MISSES:
                print(f"{gpu_run.machine}: unreachable {_MAX_MISSES} times, given up")
            busy = busy or polled is not False
        if not watch or not busy:
            return
        sleep(interval)


_MAX_MISSES = 3
"""Polls in a row a machine may be unreachable (a network outage, the backend's \
API not answering) before --watch stops following it."""


def _poll(gpu_run: "GpuRun", *, plain: bool) -> bool | None:
    """Print a machine's status, fetch, note and close what finished.

    Returns:
        Whether the machine still has something to run or a hook to close, \
        None if it couldn't be reached.
    """
    from ....exceptions import GpuRunError
    from ..._presentation import print_gpu_status

    try:
        return _poll_reachable(gpu_run, plain=plain, print_status=print_gpu_status)
    except GpuRunError as e:
        print(f"{gpu_run.machine}: unreachable ({str(e).splitlines()[0]})")
        return None


def _poll_reachable(
    gpu_run: "GpuRun", *, plain: bool, print_status: "Callable[[GpuStatus], None]"
) -> bool | None:
    from ....labs.gpu import format_report

    current = gpu_run.status()
    instance = current.instance
    if plain:
        state = instance.status if instance else "none"
        print(f"machine\t{current.machine}\t{state}")
        for entry in current.queue:
            code = "" if entry.exit_code is None else entry.exit_code
            seconds = "" if entry.seconds is None else entry.seconds
            print(f"{entry.name}\t{entry.state}\t{code}\t{seconds}")
    else:
        print_status(current)
    if instance is None:
        # Rented, as its state says, but the backend doesn't list it: unknown.
        return None if gpu_run.state() is not None else False
    if instance.status != "running":
        return False
    if current.queue:
        gpu_run.fetch()
        for run_report in gpu_run.note_finished():
            print(format_report(run_report))
    for line in gpu_run.finish_hooks():
        print(line)
    return gpu_run.hooks_pending() or any(
        entry.state != "done" for entry in current.queue
    )
