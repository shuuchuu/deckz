from pathlib import Path

from . import app


@app.command()
def report(
    notebooks: list[Path] | None = None,
    /,
    *,
    slowest: int = 5,
    plain: bool = False,
    workdir: Path = Path(),
) -> None:
    """Report on executed notebooks: exit code, run time, peak RAM, what raised.

    Reads each executed notebook and its `.done`/`.maxrss` files, as fetched
    into `out/` (every one there by default). Write a demo's outputs back
    into the repository with `deckz labs outputs EXECUTED NOTEBOOK`.

    Args:
        notebooks: Executed notebooks to report on, instead of every fetched one
        slowest: How many of each notebook's slowest cells to list under --plain
        plain: Compact, stable lines (also each notebook's slowest cells), for
            a script or an agent, instead of a table
        workdir: Path to move into before running the command

    """
    from ....configuring.settings import GlobalSettings
    from ....labs.gpu import GpuRun, format_report
    from ....labs.gpu import report as report_run
    from ..._presentation import print_gpu_reports

    out = GpuRun(GlobalSettings.from_yaml(workdir)).directory / "out"
    paths = notebooks or sorted(out.glob("*.ipynb"))
    runs = [report_run(path, slowest=slowest) for path in paths]
    if plain:
        for run in runs:
            print(format_report(run))
    else:
        print_gpu_reports(runs)
