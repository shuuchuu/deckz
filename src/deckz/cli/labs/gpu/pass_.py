from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from cyclopts import Parameter

from . import Gpus, app

if TYPE_CHECKING:
    from ....labs import gpu_pass
    from ....labs.gpu import RunReport


@app.command(name="pass")
def pass_(
    notebooks: Annotated[tuple[Path, ...], Parameter(show_default=False)] = (),
    /,
    *,
    short: bool = False,
    max_hours: float = 4.0,
    write_outputs: bool = False,
    dry_run: bool = False,
    json: bool = False,
    gpu: Gpus = None,
    interval: int = 60,
    machine: str = "main",
    workdir: Path = Path(),
) -> None:
    """Run notebooks on a machine rented for them, then destroy it, always.

    Does what `up`, `queue`, `run`, `status --watch`, `fetch` and `down` do
    one by one: rents the cheapest offer, runs the notebooks, notes each
    finished run's report in the machine's `notes.md` and prints it, then
    destroys the machine: when the runs are done, when one fails, past
    --max-hours from the rental, and on Ctrl-C, SIGTERM or SIGHUP, whenever
    it comes (renting included; only the first one stops it). Refuses a
    machine already rented (it would be destroyed at the end) or that
    another pass is running, and refuses a notebook it couldn't run before
    renting anything. Exits 1 when a run failed or didn't finish.

    Args:
        notebooks: Notebooks to run, or directories to search for them
        short: Set each notebook's `SHORT_RUN = False` line to `True` (a
            notebook without exactly one is refused)
        max_hours: The ceiling: the machine is destroyed this long after it
            was rented, whatever still runs
        write_outputs: Write each run's outputs back into its notebook
            when it exited 0 with no cell raising (but those tagged
            `raises-exception`) nor shell command failing, as `deckz labs
            outputs` does (overwrites them, then runs `labs.outputs.hooks`;
            full runs of demos only)
        dry_run: Rent nothing: print the offer it would rent now, each
            notebook's last run time (from the machines' notes) and the
            estimated cost
        json: With --dry-run, print one JSON object: `machine`, `gpu`,
            `price_per_hour`, `location` (null when nothing is on offer),
            `max_hours`, `ceiling_cost`, `setup_minutes`, `estimated_hours`
            and `estimated_cost` (null when a notebook never ran), and
            `notebooks`, each with its `notebook`, `name` and `last_seconds`
        gpu: GPU names to rent instead of `labs.gpu.gpus`, in order of
            preference: `--gpu RTX_A4000 RTX_3090`, or `--gpu RTX_A4000 --gpu
            RTX_3090`; notebooks written right after them are told apart (a
            path: an `.ipynb` file, with a `/`, or one that exists)
        interval: Seconds between two polls of the queue
        machine: Name of the machine, to run several at once
        workdir: Path to move into before running the command

    Raises:
        GpuRunError: When a run failed (a cell raised included), didn't
            finish, or an outputs hook failed on its notebook.

    """
    import json as json_module

    from ....configuring.settings import GlobalSettings
    from ....exceptions import GpuRunError
    from ....labs import gpu_pass
    from ....labs.gpu import GpuRun
    from ....labs.notebook import notebook_paths

    gpus, paths = _split_gpus(gpu or ())
    settings = GlobalSettings.from_yaml(workdir)
    gpu_run = GpuRun(settings, machine=machine)
    found = list(notebook_paths([*notebooks, *paths]))
    if dry_run:
        gpu_pass.check(gpu_run, found, short=short, write_outputs=write_outputs)
        planned = gpu_pass.plan(
            gpu_run, settings, found, short=short, max_hours=max_hours, gpus=gpus
        )
        if json:
            print(json_module.dumps(planned.as_json(settings.paths.git_dir), indent=2))
        else:
            _print_plan(planned)
        return
    result = gpu_pass.run(
        gpu_run,
        settings,
        found,
        short=short,
        max_hours=max_hours,
        write_outputs=write_outputs,
        gpus=gpus,
        interval=interval,
    )
    problems = [_failure(run) for run in result.failed]
    problems += [f"{name} didn't finish" for name in result.unfinished]
    if result.hook_failures:
        # Each was reported in full as it happened.
        problems.append(
            f"outputs hooks failed on {len(result.hook_failures)} notebook(s),"
            " as reported above"
        )
    if problems:
        ceiling = (
            " (ceiling reached: raise --max-hours)" if result.ceiling_reached else ""
        )
        msg = f"{'; '.join(problems)}{ceiling}: see `deckz labs gpu report`"
        raise GpuRunError(msg)


def _split_gpus(values: Sequence[str]) -> tuple[tuple[str, ...], tuple[Path, ...]]:
    # `--gpu A B nb.ipynb` hands the notebook to --gpu, which takes every value
    # up to the next option: a path is never a GPU name (`RTX_A4000`).
    gpus: list[str] = []
    paths: list[Path] = []
    for value in values:
        path = Path(value)
        if path.suffix == ".ipynb" or "/" in value or path.exists():
            paths.append(path)
        else:
            gpus.append(value)
    return tuple(gpus), tuple(paths)


def _failure(run: "RunReport") -> str:
    if run.exit_code != 0:
        return f"{run.path.name} exited {run.exit_code}"
    cells = sorted(
        {e.index for e in run.errors} | {s.index for s in run.shell_failures}
    )
    listed = ", ".join(f"[{index}]" for index in cells)
    return f"{run.path.name}: cell(s) {listed} raised or ran a failing command"


def _print_plan(planned: "gpu_pass.PassPlan") -> None:
    offer = planned.offer
    if offer is None:
        print(f"{planned.machine}: nothing on offer now")
    else:
        print(
            f"{planned.machine}: would rent: {offer.gpu} at ${offer.price:.3f}/h"
            f" ({offer.location})"
        )
    for run in planned.runs:
        last = "never ran" if run.last_seconds is None else f"{run.last_seconds} s"
        print(f"  {run.notebook}: last run {last}")
    hours, cost = planned.estimated_hours, planned.estimated_cost
    if hours is not None:
        dollars = "" if cost is None else f", ${cost:.2f}"
        print(f"estimate: {hours:.2f} h{dollars} (renting and booting included)")
    ceiling = planned.ceiling_cost
    dollars = "" if ceiling is None else f", ${ceiling:.2f} at most"
    print(f"ceiling: {planned.max_hours:g} h{dollars}")
