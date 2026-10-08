from pathlib import Path

from . import app


@app.command()
def down(*, machine: str | None = None, workdir: Path = Path()) -> None:
    """Destroy the machines: nothing is billed afterwards.

    Fetch what you need first: a machine's disk goes with it. The hook of a
    run it held runs then, and the notebooks held for it are dropped.

    Args:
        machine: Destroy only this machine, instead of every one rented
        workdir: Path to move into before running the command

    """
    from ....configuring.settings import GlobalSettings
    from ....labs.gpu import GpuRun, machines

    settings = GlobalSettings.from_yaml(workdir)
    names = [machine] if machine else machines(settings)
    if not names:
        print("no machine")
    for name in names:
        destroyed = GpuRun(settings, machine=name).down()
        print(
            f"{name}: no machine"
            if destroyed is None
            else f"{name}: instance {destroyed} destroyed"
        )
