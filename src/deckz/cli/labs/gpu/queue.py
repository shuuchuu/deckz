from pathlib import Path

from . import app


@app.command()
def queue(
    notebooks: list[Path], /, *, short: bool = False, workdir: Path = Path()
) -> None:
    """Send notebooks to the machine's queue.

    Each is queued as `<topic>__<lab>__<file>.<full|short>.ipynb`, after its
    path under the notebooks directory. A queue already running picks them
    up; otherwise start it with `deckz labs gpu run`.

    Args:
        notebooks: The notebooks to run
        short: Set the notebook's `SHORT_RUN = False` line to `True` (a
            notebook without exactly one is refused)
        workdir: Path to move into before running the command

    """
    from ....configuring.settings import GlobalSettings
    from ....labs.gpu import GpuRun

    names = GpuRun(GlobalSettings.from_yaml(workdir)).queue(notebooks, short=short)
    for name in names:
        print(f"queued {name}")
