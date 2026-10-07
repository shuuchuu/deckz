from pathlib import Path

from . import app


@app.command()
def fetch(*, workdir: Path = Path()) -> None:
    """Copy the machine's executed notebooks to `out/` (only what changed).

    Args:
        workdir: Path to move into before running the command

    """
    from ....configuring.settings import GlobalSettings
    from ....labs.gpu import GpuRun

    print(f"fetched into {GpuRun(GlobalSettings.from_yaml(workdir)).fetch()}")
