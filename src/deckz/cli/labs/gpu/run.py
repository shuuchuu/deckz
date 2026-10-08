from pathlib import Path

from . import app


@app.command()
def run(
    *, timeout: int = 3 * 3600, machine: str = "main", workdir: Path = Path()
) -> None:
    """Start the machine's queue, detached from this session.

    Runs each queued notebook not run yet, one after the other, each in a
    fresh `/content` and kernel, pinned to `labs.gpu.cpus` CPUs, saved after
    every cell. Rerun it after an interruption: it resumes at the first
    notebook not finished, and does nothing while the queue runs.

    Args:
        timeout: Seconds after which a notebook's run is killed
        machine: Name of the machine, to run several at once
        workdir: Path to move into before running the command

    """
    from ....configuring.settings import GlobalSettings
    from ....labs.gpu import GpuRun

    settings = GlobalSettings.from_yaml(workdir)
    print(GpuRun(settings, machine=machine).start(timeout=timeout))
