from pathlib import Path

from . import app


@app.command()
def down(*, workdir: Path = Path()) -> None:
    """Destroy the machine: nothing is billed afterwards.

    Fetch what you need first: the machine's disk goes with it.

    Args:
        workdir: Path to move into before running the command

    """
    from ....configuring.settings import GlobalSettings
    from ....labs.gpu import GpuRun

    destroyed = GpuRun(GlobalSettings.from_yaml(workdir)).down()
    print("no machine" if destroyed is None else f"instance {destroyed} destroyed")
