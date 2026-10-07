from pathlib import Path

from . import app


@app.command()
def up(*, gpu: list[str] | None = None, workdir: Path = Path()) -> None:
    """Rent a machine, wait for it to boot and accept SSH, and check its GPU.

    Rents the cheapest reliable single-GPU offer of the first GPU of
    `labs.gpu.gpus` (or of GPU) on offer. A machine that doesn't boot in
    `labs.gpu.boot_minutes` is destroyed and never rented again. Reuses the
    machine already rented, if any. It bills until `deckz labs gpu down`.

    Args:
        gpu: GPU names to rent instead of `labs.gpu.gpus`, e.g. RTX_A4000
        workdir: Path to move into before running the command

    """
    from ....configuring.settings import GlobalSettings
    from ....labs.gpu import GpuRun

    print(GpuRun(GlobalSettings.from_yaml(workdir)).up(gpu or ()))
