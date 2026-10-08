from pathlib import Path
from typing import TYPE_CHECKING

from . import app

if TYPE_CHECKING:
    from ....labs.gpu import GpuRun


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
    while True:
        busy = [_poll(gpu_run, plain=plain) for gpu_run in runs]
        if not watch or not any(busy):
            return
        sleep(interval)


def _poll(gpu_run: "GpuRun", *, plain: bool) -> bool:
    """Print a machine's status, fetch, note and close what finished.

    Returns:
        Whether the machine still has something to run or a hook to close.
    """
    from ....labs.gpu import format_report
    from ..._presentation import print_gpu_status

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
        print_gpu_status(current)
    if instance is None or instance.status != "running":
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
