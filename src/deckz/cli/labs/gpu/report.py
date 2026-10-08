from pathlib import Path

from . import app


@app.command()
def report(
    notebooks: list[Path] | None = None,
    /,
    *,
    slowest: int = 5,
    plain: bool = False,
    machine: str | None = None,
    workdir: Path = Path(),
) -> None:
    """Report on executed notebooks: exit code, run time, peak RAM, what raised.

    Reads each executed notebook and its `.done`/`.maxrss` files, as fetched
    into a machine's `out/` (every one fetched by default). Write a demo's
    outputs back into the repository with `deckz labs outputs EXECUTED
    NOTEBOOK`.

    Args:
        notebooks: Executed notebooks to report on, instead of every fetched one
        slowest: How many of each notebook's slowest cells to list under --plain
        plain: Compact, stable lines (also each notebook's slowest cells), for
            a script or an agent, instead of a table
        machine: Report only on this machine's notebooks, instead of every
            machine's, rented or not anymore
        workdir: Path to move into before running the command

    """
    from ....configuring.settings import GlobalSettings
    from ....labs.gpu import GpuRun, format_report
    from ....labs.gpu import report as report_run
    from ..._presentation import print_gpu_reports

    settings = GlobalSettings.from_yaml(workdir)
    if machine:
        outs = [GpuRun(settings, machine=machine).directory / "out"]
    else:
        root = settings.paths.labs_gpu_dir
        outs = sorted(root.glob("*/out")) if root.is_dir() else []
    paths = notebooks or [path for out in outs for path in sorted(out.glob("*.ipynb"))]
    runs = [report_run(path, slowest=slowest) for path in paths]
    if plain:
        for run in runs:
            print(format_report(run))
    else:
        print_gpu_reports(runs)
