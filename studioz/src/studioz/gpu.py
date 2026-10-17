"""GPU passes: the modal confirming one, the pass as a job, the machines billing.

A pass rents a machine that bills until it's destroyed, so it starts only
from a modal giving the GPU, its price, the estimate and the ceiling (the
workspace's `deckz labs gpu pass --dry-run --json`), its button naming the
cost; then it runs as a job of its own lane (`studioz.jobs`), every option
spelled out, deckz destroying the machine at its end, whatever the end.
studioz's agent can't start one (`studioz.agent`).

The status bar shows each machine billing, from what the workspace keeps of
its machines (`deckz labs gpu status --plain --offline`, run again only when
a machine's `state.json` changes: the bar polls), so that a machine a crash
left rented shows after a restart too; "Arrêter la machine" stops the pass
running it, else destroys it (`deckz labs gpu down`).
"""

import json
import math
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from deckz.configuring.settings import GlobalSettings
from deckz.exceptions import DeckzError

from .jobs import tidy
from .watches import workspace_environment

MACHINE = "main"
"""The machine a workspace's passes rent: one at a time, as its lane runs them."""

_PLAN_TIMEOUT = 120
_STATUS_TIMEOUT = 60
_DEFAULT_CEILING = 4.0
"""deckz's, when no earlier run gives an estimate."""


def _deckz(workspace: Path) -> str:
    return str(workspace / ".venv" / "bin" / "deckz")


def _error(result: subprocess.CompletedProcess[str], workspace: Path) -> str:
    lines = (result.stderr or result.stdout).strip().splitlines()
    error = tidy(lines[-1]) if lines else f"code {result.returncode}"
    return error.replace(f"{workspace}/", "")


@dataclass(frozen=True)
class PlannedNotebook:
    file: str
    last_seconds: int | None
    """Its last successful run's time, None if it never ran (so short)."""


@dataclass(frozen=True)
class Plan:
    """What a pass would rent now, as deckz's dry run says."""

    gpu: str | None = None
    """None when nothing is on offer."""
    price: float | None = None
    """Dollars per hour."""
    location: str | None = None
    setup_minutes: int = 0
    estimated_hours: float | None = None
    """None when a notebook never ran this way."""
    notebooks: tuple[PlannedNotebook, ...] = ()
    error: str | None = None
    """Why deckz refused or couldn't tell (a machine already rented…)."""

    def ceiling(self, chosen: float | None) -> float:
        """The ceiling to offer: the person's, else twice the estimate.

        Returns:
            Hours: twice the estimate rounded up to the half hour, at least \
            one, or deckz's default without an estimate.
        """
        if chosen:
            return chosen
        if self.estimated_hours is None:
            return _DEFAULT_CEILING
        return max(1.0, math.ceil(self.estimated_hours * 4) / 2)

    def cost(self, hours: float | None) -> float | None:
        if hours is None or self.price is None:
            return None
        return hours * self.price


def plan(
    workspace: Path, files: Sequence[str], *, short: bool, write_outputs: bool
) -> Plan:
    """What a pass of `files` would rent now, without renting.

    Returns:
        The offer and the estimate, or why deckz refuses the pass.
    """
    command = [
        _deckz(workspace),
        "labs",
        "gpu",
        "pass",
        *files,
        "--short" if short else "--no-short",
        "--write-outputs" if write_outputs else "--no-write-outputs",
        "--machine",
        MACHINE,
        "--dry-run",
        "--json",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            env=workspace_environment(workspace),
            capture_output=True,
            text=True,
            timeout=_PLAN_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Plan(error=str(error))
    try:
        found = json.loads(result.stdout)
        return Plan(
            found["gpu"],
            found["price_per_hour"],
            found["location"],
            found["setup_minutes"],
            found["estimated_hours"],
            tuple(
                PlannedNotebook(n["notebook"], n["last_seconds"])
                for n in found["notebooks"]
            ),
        )
    except (ValueError, KeyError, TypeError):
        return Plan(error=_error(result, workspace))


def pass_steps(
    workspace: Path,
    files: Sequence[str],
    *,
    short: bool,
    write_outputs: bool,
    max_hours: float,
) -> list[list[str]]:
    """`deckz labs gpu pass`, every option spelled out.

    Returns:
        The job's one step, to run in the workspace.
    """
    return [
        [
            _deckz(workspace),
            "labs",
            "gpu",
            "pass",
            *files,
            "--short" if short else "--no-short",
            "--write-outputs" if write_outputs else "--no-write-outputs",
            "--max-hours",
            f"{max_hours:g}",
            "--machine",
            MACHINE,
        ]
    ]


def down_steps(workspace: Path, machine: str) -> list[list[str]]:
    """`deckz labs gpu down` of one machine.

    Returns:
        The job's one step, to run in the workspace.
    """
    return [[_deckz(workspace), "labs", "gpu", "down", "--machine", machine]]


@dataclass(frozen=True)
class Machine:
    """A machine rented, as the workspace keeps it: it bills."""

    name: str
    gpu: str
    price: float | None
    """Dollars per hour, None for a machine rented before deckz kept it."""
    rented_at: datetime | None

    def hours(self, now: datetime) -> float | None:
        if self.rented_at is None:
            return None
        return max(0.0, (now - self.rented_at).total_seconds() / 3600)

    def cost(self, now: datetime) -> float | None:
        hours = self.hours(now)
        return None if hours is None or self.price is None else hours * self.price


@dataclass(frozen=True)
class Machines:
    machines: tuple[Machine, ...] = ()
    error: str | None = None


# Each workspace's machines directory (from its settings), and its last
# reading with the state files it was made from: the status bar polls, and
# the reading changes only when a machine is rented or destroyed.
_DIRS: dict[Path, Path] = {}
_READINGS: dict[Path, tuple[tuple[tuple[str, int], ...], Machines]] = {}


def _states(workspace: Path) -> tuple[tuple[str, int], ...]:
    directory = _DIRS.get(workspace)
    if directory is None:
        try:
            directory = GlobalSettings.from_yaml(workspace).paths.labs_gpu_dir
        except (DeckzError, OSError, ValueError):
            directory = workspace / ".run" / "gpu"
        _DIRS[workspace] = directory
    if not directory.is_dir():
        return ()
    found = []
    for state in sorted(directory.glob("*/state.json")):
        try:
            found.append((str(state), state.stat().st_mtime_ns))
        except OSError:
            continue  # Destroyed meanwhile.
    return tuple(found)


def machines(workspace: Path) -> Machines:
    """The machines the workspace keeps as rented: they bill.

    Returns:
        Them, or why deckz couldn't tell; nothing asked of deckz while no \
        machine's state changed.
    """
    states = _states(workspace)
    if not states:
        _READINGS.pop(workspace, None)
        return Machines()
    cached = _READINGS.get(workspace)
    if cached is not None and cached[0] == states:
        return cached[1]
    found = _machines(workspace)
    if not found.error:
        _READINGS[workspace] = (states, found)
    return found


def _machines(workspace: Path) -> Machines:
    command = [_deckz(workspace), "labs", "gpu", "status", "--plain", "--offline"]
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            env=workspace_environment(workspace),
            capture_output=True,
            text=True,
            timeout=_STATUS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Machines(error=str(error))
    if result.returncode:
        return Machines(error=_error(result, workspace))
    found = []
    for line in result.stdout.splitlines():
        fields = [*line.split("\t"), "", "", "", "", ""][:6]
        if fields[0] != "machine" or fields[2] in {"none", ""}:
            continue
        _, name, _, gpu, price, rented_at = fields
        try:
            when = datetime.fromisoformat(rented_at) if rented_at else None
            dollars = float(price) if price else None
        except ValueError:
            when, dollars = None, None
        found.append(Machine(name, gpu, dollars, when))
    return Machines(tuple(found))
