"""A whole GPU pass in one command: rent, run, follow, fetch, note, destroy.

`deckz labs gpu pass` does what `up`, `queue`, `run`, `status --watch`,
`fetch` and `down` do one by one, and always destroys the machine at the end:
on success, on failure, past its ceiling (`max_hours`, counted from the
rental, since the machine bills from then), and on Ctrl-C or SIGTERM (what
studioz sends to stop a job). The destruction itself can't be interrupted:
a machine left running bills until someone notices.

Its dry run (`plan`) says what it would cost: the offer it would rent now,
and each notebook's last successful run time, from the machines' `notes.md`
(this checkout's, and its main checkout's when it's a worktree: a workspace
starts with no notes of its own).
"""

import re
import signal
import threading
import time
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING

from ..exceptions import GpuRunError, WorktreeError
from .gpu import GpuRun, Offer, RunReport, format_report

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings

_logger = getLogger(__name__)

SETUP_MINUTES = 10
"""What an estimate adds for renting and booting the machine (pulling Colab's \
image, snapshotting its packages): a few minutes, up to ten."""

_MAX_MISSES = 3
"""Polls in a row the machine may be unreachable before the pass gives up."""

_NOTE = re.compile(r"^Noted (?P<stamp>.+):$")
_RUN = re.compile(r"^#### (?P<name>\S+): exit (?P<code>\S+), (?P<seconds>\S+) s,")


class GpuPassStoppedError(GpuRunError):
    """The pass was stopped (SIGTERM): its machine was destroyed."""


@dataclass(frozen=True)
class PlannedRun:
    notebook: Path
    name: str
    """Its name on the machine (`GpuRun.queued_name`)."""
    last_seconds: int | None
    """Its last successful run's time, None if it never ran (here)."""


@dataclass(frozen=True)
class PassPlan:
    machine: str
    offer: Offer | None
    """What would be rented now, None if nothing is on offer."""
    runs: tuple[PlannedRun, ...]
    max_hours: float

    @property
    def estimated_hours(self) -> float | None:
        """Renting and booting, then each run's last time.

        Returns:
            The hours, None if a notebook never ran.
        """
        if any(run.last_seconds is None for run in self.runs):
            return None
        seconds = sum(run.last_seconds or 0 for run in self.runs)
        return min(SETUP_MINUTES / 60 + seconds / 3600, self.max_hours)

    @property
    def estimated_cost(self) -> float | None:
        hours = self.estimated_hours
        if hours is None or self.offer is None:
            return None
        return hours * self.offer.price

    @property
    def ceiling_cost(self) -> float | None:
        return None if self.offer is None else self.max_hours * self.offer.price

    def as_json(self, git_dir: Path) -> dict[str, object]:
        """The plan, for `--dry-run --json`.

        Returns:
            Its fields, paths relative to `git_dir`, money in dollars.
        """
        offer = self.offer
        return {
            "machine": self.machine,
            "gpu": offer.gpu if offer else None,
            "price_per_hour": offer.price if offer else None,
            "location": offer.location if offer else None,
            "max_hours": self.max_hours,
            "ceiling_cost": self.ceiling_cost,
            "setup_minutes": SETUP_MINUTES,
            "estimated_hours": self.estimated_hours,
            "estimated_cost": self.estimated_cost,
            "notebooks": [
                {
                    "notebook": _relative(run.notebook, git_dir),
                    "name": run.name,
                    "last_seconds": run.last_seconds,
                }
                for run in self.runs
            ],
        }


@dataclass
class PassResult:
    instance: int | None = None
    """The instance destroyed."""
    reports: list[RunReport] = field(default_factory=list)
    unfinished: list[str] = field(default_factory=list)
    """What the queue hadn't finished when the pass ended."""
    ceiling_reached: bool = False
    written: list[Path] = field(default_factory=list)
    """The notebooks whose outputs were written back."""

    @property
    def failed(self) -> list[RunReport]:
        return [run for run in self.reports if run.exit_code != 0]


def _relative(path: Path, root: Path) -> str:
    resolved = path.resolve()
    if resolved.is_relative_to(root.resolve()):
        return resolved.relative_to(root.resolve()).as_posix()
    return str(path)


def notes_dirs(settings: "GlobalSettings") -> list[Path]:
    """Where the machines' notes are: this checkout's, and its main checkout's.

    Returns:
        The directories holding one directory per machine.
    """
    from ..worktrees import main_checkout

    git_dir = settings.paths.git_dir
    found = [settings.paths.labs_gpu_dir]
    try:
        main = main_checkout(git_dir)
    except WorktreeError:  # Not a git checkout: its own notes only.
        return found
    if main.resolve() != git_dir.resolve():
        relative = settings.paths.labs_gpu_dir.resolve().relative_to(git_dir.resolve())
        found.append(main / relative)
    return found


def last_runs(directories: Sequence[Path]) -> dict[str, int]:
    """Each notebook's last successful run time, from the machines' notes.

    Returns:
        Seconds, by queued name (`<topic>__<lab>__<file>.<full|short>.ipynb`).
    """
    found: dict[str, tuple[str, int]] = {}
    for directory in directories:
        for notes in sorted(directory.glob("*/notes.md")) if directory.is_dir() else ():
            stamp = ""
            for line in notes.read_text(encoding="utf-8").splitlines():
                if note := _NOTE.match(line):
                    stamp = note["stamp"]
                elif (run := _RUN.match(line)) and run["code"] == "0":
                    seconds = run["seconds"]
                    if seconds.isdigit() and stamp >= found.get(run["name"], ("",))[0]:
                        found[run["name"]] = (stamp, int(seconds))
    return {name: seconds for name, (_, seconds) in found.items()}


def check(
    gpu_run: GpuRun,
    notebooks: Sequence[Path],
    *,
    short: bool,
    write_outputs: bool,
) -> None:
    """Refuse, before renting anything, what the pass would fail on.

    Raises:
        GpuRunError: If the machine is already rented (the pass would destroy \
            it), a notebook is missing, outputs are asked of a short run or \
            of a hands-on notebook, or a notebook can't be queued as asked.
    """
    if gpu_run.state() is not None:
        msg = (
            f"machine {gpu_run.machine} is already rented, and a pass destroys its"
            f" machine at the end: name another one (--machine), or `deckz labs gpu"
            f" down --machine {gpu_run.machine}` once done with it"
        )
        raise GpuRunError(msg)
    if not notebooks:
        msg = "no notebook to run"
        raise GpuRunError(msg)
    if missing := [str(notebook) for notebook in notebooks if not notebook.is_file()]:
        msg = f"no such notebook: {', '.join(missing)}"
        raise GpuRunError(msg)
    if write_outputs and short:
        msg = (
            "--write-outputs keeps a full run's outputs only: drop --short, or"
            " --write-outputs"
        )
        raise GpuRunError(msg)
    if write_outputs:
        for notebook in notebooks:
            if notebook.stem.rpartition("-")[0] == "hands-on":
                msg = (
                    f"{notebook}: a hands-on notebook stores no outputs (lab-outputs):"
                    " leave it out, or drop --write-outputs"
                )
                raise GpuRunError(msg)
    gpu_run.check(notebooks, short=short)


def plan(
    gpu_run: GpuRun,
    settings: "GlobalSettings",
    notebooks: Sequence[Path],
    *,
    short: bool,
    max_hours: float,
    gpus: Sequence[str] = (),
) -> PassPlan:
    """What a pass would rent now, and how long its notebooks last took.

    Returns:
        The plan.
    """
    known = last_runs(notes_dirs(settings))
    runs = []
    for notebook in notebooks:
        name = gpu_run.queued_name(notebook, short=short)
        runs.append(PlannedRun(notebook, name, known.get(name)))
    offer = gpu_run.cheapest(gpus)
    return PassPlan(gpu_run.machine, offer, tuple(runs), max_hours)


@contextmanager
def _stopped_by_sigterm() -> Generator[None]:
    # SIGTERM raises, as Ctrl-C does, so that the machine is destroyed.
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def stop(signum: int, _: FrameType | None) -> None:
        msg = f"stopped ({signal.Signals(signum).name}): the machine was destroyed"
        raise GpuPassStoppedError(msg)

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


@contextmanager
def _uninterrupted() -> Generator[None]:
    # Ctrl-C and SIGTERM wait until the machine is destroyed.
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    blocked = {signal.SIGINT, signal.SIGTERM}
    signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, blocked)


def run(
    gpu_run: GpuRun,
    settings: "GlobalSettings",
    notebooks: Sequence[Path],
    *,
    short: bool = False,
    max_hours: float,
    write_outputs: bool = False,
    gpus: Sequence[str] = (),
    interval: float = 60,
    report: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> PassResult:
    """Run the notebooks on a machine rented for them, then destroy it.

    Args:
        gpu_run: The machine, not rented yet.
        settings: The repository's settings.
        notebooks: The notebooks to run.
        short: Run them short (`SHORT_RUN = True`).
        max_hours: The ceiling: past it, from the rental on, the machine is \
            destroyed, whatever still runs.
        write_outputs: Write each run's outputs back into its notebook, \
            when it exited 0 (`deckz labs outputs`), once the machine is gone.
        gpus: GPUs to rent instead of `labs.gpu.gpus`.
        interval: Seconds between two polls of the queue.
        report: Prints each run's report as it's noted, and what's held, not \
            finished or written back (progress goes to the log).
        clock: `time.monotonic`, which tests replace.
        sleep: `time.sleep`, which tests replace.

    Returns:
        The runs' reports, what didn't finish, and what was written back.

    Raises:
        GpuRunError: If the machine couldn't be destroyed (it may still bill).
    """
    check(gpu_run, notebooks, short=short, write_outputs=write_outputs)
    result = PassResult()
    names: dict[str, Path] = {}
    deadline = clock() + max_hours * 3600
    try:
        with _stopped_by_sigterm():
            _logger.info("Renting a machine, destroyed after %g h at most", max_hours)
            _logger.info("Machine up: %s", gpu_run.up(gpus))
            queued, held = gpu_run.queue(notebooks, short=short)
            names = {
                gpu_run.queued_name(notebook, short=short): notebook
                for notebook in notebooks
            }
            for notebook in held:
                report(f"held {notebook} until its hook's current run is done")
            remaining = max(60, int(deadline - clock()))
            gpu_run.start(timeout=remaining)
            _logger.info("Running %s notebook(s)", len(queued))
            _follow(gpu_run, result, deadline, interval, report, clock, sleep)
    finally:
        with _uninterrupted():
            try:
                result.instance = gpu_run.down()
            except GpuRunError as error:
                msg = (
                    f"{error}\nThe machine may still bill: `deckz labs gpu down"
                    f" --machine {gpu_run.machine}`, and check the backend's instances"
                )
                raise GpuRunError(msg) from error
            if result.instance is not None:
                _logger.info(
                    "Instance %s destroyed: nothing is billed", result.instance
                )
    if write_outputs:
        _write_back(settings, gpu_run, result, names, report)
    return result


def _follow(
    gpu_run: GpuRun,
    result: PassResult,
    deadline: float,
    interval: float,
    report: Callable[[str], None],
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> None:
    # Poll until the queue and its hooks are done, the ceiling is reached,
    # or the machine is lost.
    misses = 0
    while True:
        try:
            current = gpu_run.status()
            if current.instance is None or current.instance.status != "running":
                state = current.instance.status if current.instance else "gone"
                msg = f"the machine stopped running ({state})"
                raise GpuRunError(msg)
            gpu_run.fetch()
            for noted in gpu_run.note_finished():
                result.reports.append(noted)
                report(format_report(noted))
            for line in gpu_run.finish_hooks():
                report(line)
            misses = 0
        except GpuRunError as error:
            misses += 1
            if misses >= _MAX_MISSES:
                raise
            _logger.warning("Machine unreachable (%s)", str(error).splitlines()[0])
            sleep(interval)
            continue
        result.unfinished = [e.name for e in current.queue if e.state != "done"]
        if not result.unfinished and not gpu_run.hooks_pending():
            return
        left = deadline - clock()
        if left <= 0:
            result.ceiling_reached = True
            report(f"ceiling reached: {', '.join(result.unfinished)} not finished")
            return
        sleep(min(interval, left))


def _write_back(
    settings: "GlobalSettings",
    gpu_run: GpuRun,
    result: PassResult,
    names: dict[str, Path],
    report: Callable[[str], None],
) -> None:
    from .outputs import write_outputs

    for run_report in result.reports:
        notebook = names.get(run_report.path.name)
        if notebook is None or run_report.exit_code != 0:
            continue
        write_outputs(
            gpu_run.directory / "out" / run_report.path.name,
            notebook,
            solution_heading=settings.labs.solution_heading,
        )
        result.written.append(notebook)
        report(f"wrote the outputs of {run_report.path.name} into {notebook}")
