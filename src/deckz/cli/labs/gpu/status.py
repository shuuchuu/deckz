from pathlib import Path

from . import app


@app.command()
def status(
    *,
    watch: bool = False,
    interval: int = 120,
    plain: bool = False,
    workdir: Path = Path(),
) -> None:
    """Show the machine's state and each queued notebook's.

    With --watch, polls until every queued notebook is done: each time,
    fetches the executed notebooks and appends a report of each newly
    finished one to `notes.md` (in `labs_gpu_dir`), so an interrupted session
    loses nothing, and prints those reports.

    Args:
        watch: Keep polling, fetching and noting finished runs until the
            queue is done
        interval: Seconds between two polls under --watch
        plain: One tab-separated line per notebook (name, state, exit code,
            seconds), for a script or an agent, instead of a table
        workdir: Path to move into before running the command

    """
    from time import sleep

    from ....configuring.settings import GlobalSettings
    from ....labs.gpu import GpuRun, format_report
    from ..._presentation import print_gpu_status

    gpu_run = GpuRun(GlobalSettings.from_yaml(workdir))
    while True:
        current = gpu_run.status()
        if plain:
            instance = current.instance
            print(f"machine\t{instance.status if instance else 'none'}")
            for entry in current.queue:
                code = "" if entry.exit_code is None else entry.exit_code
                seconds = "" if entry.seconds is None else entry.seconds
                print(f"{entry.name}\t{entry.state}\t{code}\t{seconds}")
        else:
            print_gpu_status(current)
        running = current.instance is not None and current.instance.status == "running"
        if running and current.queue:
            gpu_run.fetch()
            for run_report in gpu_run.note_finished():
                print(format_report(run_report))
        finished = all(entry.state == "done" for entry in current.queue)
        if not watch or not running or finished:
            return
        sleep(interval)
