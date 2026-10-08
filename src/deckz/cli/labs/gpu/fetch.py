from pathlib import Path

from . import app


@app.command()
def fetch(*, machine: str = "main", workdir: Path = Path()) -> None:
    """Copy the machine's executed notebooks to `out/` (only what changed).

    Secrets the notebooks were given are redacted from what is copied.

    Args:
        machine: Name of the machine, to run several at once
        workdir: Path to move into before running the command

    """
    from ....configuring.settings import GlobalSettings
    from ....labs.gpu import GpuRun

    settings = GlobalSettings.from_yaml(workdir)
    print(f"fetched into {GpuRun(settings, machine=machine).fetch()}")
