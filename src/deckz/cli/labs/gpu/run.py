from pathlib import Path

from . import app


@app.command()
def run(*, timeout: int = 3 * 3600, workdir: Path = Path()) -> None:
    """Start the machine's queue, detached from this session.

    Runs each queued notebook not run yet, one after the other, each in a
    fresh `/content` and kernel, pinned to `labs.gpu.cpus` CPUs, saved after
    every cell. Rerun it after an interruption: it resumes at the first
    notebook not finished, and does nothing while the queue runs.

    Args:
        timeout: Seconds after which a notebook's run is killed
        workdir: Path to move into before running the command

    """
    from ....configuring.settings import GlobalSettings
    from ....labs.gpu import GpuRun

    print(GpuRun(GlobalSettings.from_yaml(workdir)).start(timeout=timeout))
