from pathlib import Path

from . import app


@app.command()
def queue(
    notebooks: list[Path],
    /,
    *,
    short: bool = False,
    machine: str = "main",
    workdir: Path = Path(),
) -> None:
    """Send notebooks to the machine's queue.

    Each is queued as `<topic>__<lab>__<file>.<full|short>.ipynb`, after its
    path under the notebooks directory. A queue already running picks them
    up; otherwise start it with `deckz labs gpu run`.

    A notebook's metadata (`labs.gpu.metadata_key`) can ask for variables
    and secrets, filled from the environment or `.env` in the copy sent (a
    secret is redacted from what comes back), and for a hook of
    `labs.gpu.hooks`, run here before the notebook is sent and once its run
    is done (`status`, `down`). A notebook naming a hook another run still
    holds is held, and sent by `status` once that run's hook ran.

    Args:
        notebooks: The notebooks to run
        short: Set the notebook's `SHORT_RUN = False` line to `True` (a
            notebook without exactly one is refused)
        machine: Name of the machine, to run several at once
        workdir: Path to move into before running the command

    """
    from ....configuring.settings import GlobalSettings
    from ....labs.gpu import GpuRun

    settings = GlobalSettings.from_yaml(workdir)
    queued, held = GpuRun(settings, machine=machine).queue(notebooks, short=short)
    for name in queued:
        print(f"queued {name}")
    for notebook in held:
        print(f"held {notebook} until its hook's current run is done")
