"""Run lab notebooks on a rented GPU machine, the way Colab runs them.

The machine boots Colab's own runtime image by default (`labs.gpu.image`), so
the packages are Colab's, and each notebook runs on as many CPUs as Colab's
T4 runtime has (`labs.gpu.cpus`), with its peak RAM recorded to compare with
Colab's 12.7 GB. A pass rents a machine (`up`), queues notebooks (`queue`),
starts the queue (`start`), follows it (`status`, `fetch`, `note_finished`),
reports on the executed copies (`report`), and destroys the machine (`down`).
A machine bills until it is destroyed.

Renting goes through a `GpuBackend`; `VastBackend` (Vast.ai, through the
`vastai` CLI of the `deckz[gpu]` extra) is the only one. Everything else is
plain `ssh`/`scp`/`rsync` to the machine, whose state (ID, address) lives in
`GlobalPaths.labs_gpu_dir` (`state.json`), next to the staged and executed
notebooks (`in/`, `out/`), the notes on finished runs (`notes.md`) and the
machines that failed to boot (`avoid.json`, never rented again).

Lessons the defaults and scripts below encode, from runs on Vast.ai with
Colab's image: the image has no SSH host keys and its sshd listens on
127.0.0.1:2222 only, so the machine's start command runs a second sshd on
port 22; the SSH port is read from the instance's port mapping, since
`vastai ssh-url` can name a recycled container's old port; each run is
pinned to its CPUs (`taskset`, `PYTHON_CPU_COUNT`) and saved after every
cell, so a hang or an interruption keeps what ran; the queue picks up
notebooks queued while it runs.
"""

import json
import subprocess
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from logging import getLogger
from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING, Any, Protocol

from ..exceptions import GpuRunError, MissingExtraError

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings

_logger = getLogger(__name__)

Runner = Callable[..., subprocess.CompletedProcess[str]]
"""`subprocess.run`'s signature: tests pass a fake one."""

ATTEMPTS = 3
"""Machines rented in a row before `up` gives up on booting one."""

START_COMMAND = (
    "mkdir -p /run/sshd; ssh-keygen -A;"
    ' sed -e "s/^Port .*/Port 22/" -e "s/^ListenAddress .*/ListenAddress 0.0.0.0/"'
    " /etc/ssh/sshd_config > /etc/ssh/sshd_vast; /usr/sbin/sshd -f /etc/ssh/sshd_vast"
)
"""The machine's start command: Colab's image has no SSH host keys, and its \
sshd config listens on 127.0.0.1:2222 only, so start one on port 22."""

EXECUTE = """\
import resource
import sys

import nbformat
from nbclient import NotebookClient

source, target = sys.argv[1:]
nb = nbformat.read(source, as_version=4)


def save(**_):
    nbformat.write(nb, target)


client = NotebookClient(
    nb, timeout=None, kernel_name="python3", allow_errors=True, record_timing=True,
    resources={"metadata": {"path": "/content"}},
)
client.on_cell_executed = save
client.execute()
save()
# The kernel's peak memory (and its children's), in KiB.
with open(target + ".maxrss", "w") as f:
    f.write(str(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss))
"""
"""Runs one notebook on the machine, saving it after every cell."""

QUEUE = """\
#!/bin/bash
exec 9>/work/queue.lock
flock -n 9 || exit 0
# The image's environment (CUDA paths...) is the container's, PID 1's: SSH
# sessions don't have all of it.
while IFS= read -r -d '' var; do export "$var"; done < /proc/1/environ
cd /work
shopt -s nullglob
# Until nothing is left: notebooks queued while it runs are picked up too.
while true; do
  next=""
  for path in in/*.ipynb; do
    [ -e "out/$(basename "$path").done" ] || { next=$path; break; }
  done
  [ -n "$next" ] || break
  path=$next
  name=$(basename "$path")
  echo "$(date -Is) start $name"
  start=$(date +%s)
  rm -rf /content && mkdir -p /content && cp "$path" /content/
  (cd /content && PYTHON_CPU_COUNT=@CPUS@ taskset -c @CPU_LIST@ timeout @TIMEOUT@ \\
    python3 /work/execute.py "$name" "/work/out/$name") > "out/$name.log" 2>&1
  echo "$? $(( $(date +%s) - start ))" > "out/$name.done"
  echo "$(date -Is) done $name: $(cat "out/$name.done")"
done
echo "$(date -Is) queue finished"
"""
"""The machine's queue: each staged notebook not run yet, one after the other."""

_STATUS = (
    'cd /work 2>/dev/null || exit 0; for f in in/*.ipynb; do [ -e "$f" ] || continue;'
    ' n=$(basename "$f"); if [ -e "out/$n.done" ]; then'
    ' printf "%s\\tdone\\t%s\\n" "$n" "$(cat "out/$n.done")";'
    ' elif [ -e "out/$n.log" ]; then printf "%s\\trunning\\t\\n" "$n";'
    ' else printf "%s\\tqueued\\t\\n" "$n"; fi; done'
)


@dataclass(frozen=True)
class Offer:
    id: int
    gpu: str
    machine: int
    price: float
    """Dollars per hour."""
    location: str


@dataclass(frozen=True)
class InstanceInfo:
    status: str
    """`running`, `stopped`, or whatever the backend says while it starts."""
    message: str = ""
    host: str | None = None
    ssh_port: int | None = None
    gpu: str = ""
    price: float = 0.0


@dataclass
class GpuState:
    """The rented machine, as `state.json` keeps it."""

    id: int
    gpu: str
    machine: int
    host: str | None = None
    port: int | None = None


@dataclass(frozen=True)
class QueueEntry:
    name: str
    state: str
    """`queued`, `running` or `done`."""
    exit_code: int | None = None
    seconds: int | None = None


@dataclass(frozen=True)
class GpuStatus:
    instance: InstanceInfo | None
    queue: tuple[QueueEntry, ...] = ()


@dataclass(frozen=True)
class CellTiming:
    index: int
    seconds: float
    first_line: str


@dataclass(frozen=True)
class CellError:
    index: int
    name: str
    value: str


@dataclass(frozen=True)
class RunReport:
    path: Path
    exit_code: int | None
    seconds: int | None
    peak_ram_gib: float | None
    cells_ran: int
    code_cells: int
    errors: tuple[CellError, ...] = ()
    slowest: tuple[CellTiming, ...] = field(default_factory=tuple)


class GpuBackend(Protocol):
    """Rents, describes and destroys a GPU machine with SSH access."""

    def rent(self, gpus: Sequence[str], avoid: Collection[int]) -> GpuState:
        """Rent the cheapest offer of the first of `gpus` on offer.

        Args:
            gpus: GPU names, in order of preference.
            avoid: Machines never to rent.
        """
        ...

    def info(self, instance_id: int) -> InstanceInfo | None:
        """The instance's state, or None if it doesn't exist (anymore)."""
        ...

    def destroy(self, instance_id: int) -> None:
        """Destroy the instance: nothing is billed afterwards."""
        ...


class VastBackend:
    """Vast.ai, through its `vastai` CLI (`deckz[gpu]`, plus an API key)."""

    def __init__(self, settings: "GlobalSettings", run: Runner = subprocess.run):
        self._gpu = settings.labs.gpu
        self._run = run

    def _vastai(self, *args: str, check: bool = True) -> str:
        if which("vastai") is None and self._run is subprocess.run:
            msg = 'vastai is not installed, install it with `pip install "deckz[gpu]"`'
            raise MissingExtraError(msg)
        proc = self._run(["vastai", *args], capture_output=True, text=True, check=False)
        if check and proc.returncode:
            msg = f"vastai {' '.join(args[:2])} failed:\n{proc.stdout}{proc.stderr}"
            raise GpuRunError(msg)
        return proc.stdout

    def offers(self, gpu: str, avoid: Collection[int]) -> list[Offer]:
        """The offers of `gpu` matching `labs.gpu.offer_filter`, cheapest first.

        Returns:
            The offers.
        """
        excluded = "".join(f" machine_id!={machine}" for machine in avoid)
        found = json.loads(
            self._vastai(
                "search",
                "offers",
                f"gpu_name={gpu} {self._gpu.offer_filter}{excluded}",
                "--storage",
                str(self._gpu.disk_gb),
                "-o",
                "dph_total",
                "--raw",
            )
        )
        return [
            Offer(
                id=offer["id"],
                gpu=offer["gpu_name"],
                machine=offer["machine_id"],
                price=offer["dph_total"],
                location=offer.get("geolocation", ""),
            )
            for offer in found
        ]

    def rent(self, gpus: Sequence[str], avoid: Collection[int]) -> GpuState:
        """Rent the cheapest offer of the first of `gpus` on offer.

        Tries the three cheapest offers of each GPU in turn: an offer can be
        taken by someone else between the search and the rental.

        Returns:
            The rented machine.

        Raises:
            GpuRunError: If no offer could be rented.
        """
        for gpu in gpus:
            for offer in self.offers(gpu, avoid)[:3]:
                _logger.info(
                    "Renting offer %s: %s, $%.3f/h, %s",
                    offer.id,
                    offer.gpu,
                    offer.price,
                    offer.location,
                )
                out = self._vastai(
                    "create",
                    "instance",
                    str(offer.id),
                    "--image",
                    self._gpu.image,
                    "--disk",
                    str(self._gpu.disk_gb),
                    "--ssh",
                    "--direct",
                    "--onstart-cmd",
                    START_COMMAND,
                    "--label",
                    "deckz-labs-gpu",
                    "--cancel-unavail",
                    "--raw",
                    check=False,
                )
                try:
                    created = json.loads(out)
                except json.JSONDecodeError:
                    created = {}
                if created.get("success"):
                    return GpuState(
                        id=created["new_contract"], gpu=offer.gpu, machine=offer.machine
                    )
                _logger.info("Offer %s not rented: %s", offer.id, out.strip()[:200])
        msg = f"no offer rented among {', '.join(gpus)}"
        raise GpuRunError(msg)

    def info(self, instance_id: int) -> InstanceInfo | None:
        out = self._vastai("show", "instance", str(instance_id), "--raw", check=False)
        try:
            raw = json.loads(out)
        except json.JSONDecodeError:
            return None
        if not raw:
            return None
        status = raw.get("actual_status") or ""
        if raw.get("cur_state") == "stopped" and status != "running":
            status = "stopped"
        ports = (raw.get("ports") or {}).get("22/tcp") or []
        return InstanceInfo(
            status=status or "starting",
            message=raw.get("status_msg") or "",
            host=(raw.get("public_ipaddr") or "").strip() or None,
            ssh_port=int(ports[0]["HostPort"]) if ports else None,
            gpu=raw.get("gpu_name") or "",
            price=raw.get("dph_total") or 0.0,
        )

    def destroy(self, instance_id: int) -> None:
        self._vastai("destroy", "instance", str(instance_id), "-y")


class GpuRun:
    """One pass of notebooks on a rented machine, kept in `labs_gpu_dir`."""

    def __init__(
        self,
        settings: "GlobalSettings",
        backend: GpuBackend | None = None,
        run: Runner = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._gpu = settings.labs.gpu
        self._dir = settings.paths.labs_gpu_dir
        self._backend = backend if backend is not None else VastBackend(settings, run)
        self._run = run
        self._sleep = sleep

    # -- state ----------------------------------------------------------------

    @property
    def directory(self) -> Path:
        return self._dir

    @property
    def _state_file(self) -> Path:
        return self._dir / "state.json"

    @property
    def _avoid_file(self) -> Path:
        return self._dir / "avoid.json"

    def state(self) -> GpuState | None:
        """The rented machine, as `state.json` keeps it.

        Returns:
            The machine, or None if none is rented.
        """
        if not self._state_file.is_file():
            return None
        return GpuState(**json.loads(self._state_file.read_text(encoding="utf-8")))

    def _save(self, state: GpuState | None) -> None:
        if state is None:
            self._state_file.unlink(missing_ok=True)
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(asdict(state)), encoding="utf-8")

    def _avoided(self) -> list[int]:
        if not self._avoid_file.is_file():
            return []
        return json.loads(self._avoid_file.read_text(encoding="utf-8"))

    def _connected(self) -> GpuState:
        state = self.state()
        if state is None or state.host is None or state.port is None:
            msg = "no machine yet: run `deckz labs gpu up` first"
            raise GpuRunError(msg)
        return state

    # -- remote access --------------------------------------------------------

    def _ssh_options(self) -> list[str]:
        return [
            "-i",
            str(Path(self._gpu.ssh_key).expanduser()),
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={self._dir / 'known_hosts'}",
            "-o",
            "ConnectTimeout=20",
        ]

    def _ssh(self, command: str, *, check: bool = True) -> str:
        state = self._connected()
        proc = self._run(
            [
                "ssh",
                *self._ssh_options(),
                "-p",
                str(state.port),
                f"root@{state.host}",
                command,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if check and proc.returncode:
            msg = f"ssh failed ({proc.returncode}): {command[:80]}\n{proc.stderr}"
            raise GpuRunError(msg)
        return (proc.stdout or "").strip()

    def _scp(self, sources: Sequence[Path], destination: str) -> None:
        state = self._connected()
        proc = self._run(
            [
                "scp",
                *self._ssh_options(),
                "-P",
                str(state.port),
                *map(str, sources),
                f"root@{state.host}:{destination}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode:
            msg = f"scp to {destination} failed:\n{proc.stderr}"
            raise GpuRunError(msg)

    # -- the pass -------------------------------------------------------------

    def up(self, gpus: Sequence[str] = ()) -> str:
        """Rent a machine, wait for it to boot and accept SSH, and check it.

        A machine that doesn't boot within `labs.gpu.boot_minutes` (its
        image pull failed, say) is destroyed and never rented again.

        Returns:
            The machine's GPU line (`nvidia-smi -L`).

        Raises:
            GpuRunError: If no machine booted in `ATTEMPTS` rentals.
        """
        for _ in range(ATTEMPTS):
            state = self.state()
            if state is None or self._backend.info(state.id) is None:
                state = self._backend.rent(
                    tuple(gpus) or self._gpu.gpus, self._avoided()
                )
                self._save(state)
            info = self._boot(state)
            if info is not None:
                break
            self._dir.mkdir(parents=True, exist_ok=True)
            self._avoid_file.write_text(
                json.dumps([*self._avoided(), state.machine]), encoding="utf-8"
            )
            self._backend.destroy(state.id)
            self._save(None)
            _logger.warning(
                "Destroyed instance %s: machine %s avoided from now on",
                state.id,
                state.machine,
            )
        else:
            msg = f"{ATTEMPTS} machines failed to boot: check the backend's instances"
            raise GpuRunError(msg)
        state.host, state.port = info.host, info.ssh_port
        self._save(state)
        for _ in range(20):
            if self._ssh_ready():
                break
            self._sleep(15)
        return self._ssh(
            "nvidia-smi -L; mkdir -p /work/in /work/out; python3 -c 'import nbclient'"
        )

    def _ssh_ready(self) -> bool:
        state = self._connected()
        return (
            self._run(
                [
                    "ssh",
                    *self._ssh_options(),
                    "-p",
                    str(state.port),
                    f"root@{state.host}",
                    "true",
                ],
                capture_output=True,
                text=True,
                check=False,
            ).returncode
            == 0
        )

    def _boot(self, state: GpuState) -> InstanceInfo | None:
        polls = self._gpu.boot_minutes * 3
        for _ in range(polls):
            info = self._backend.info(state.id)
            if info is not None and info.status == "running":
                if info.host and info.ssh_port:
                    return info
            elif info is not None and info.status == "stopped":
                _logger.warning("Instance %s stopped: %s", state.id, info.message[:200])
                return None
            _logger.info(
                "Instance %s: %s", state.id, info.status if info else "starting"
            )
            self._sleep(20)
        _logger.warning(
            "Instance %s not running after %s minutes", state.id, self._gpu.boot_minutes
        )
        return None

    def queue(self, notebooks: Sequence[Path], *, short: bool = False) -> list[str]:
        """Stage notebooks and send them to the machine's queue.

        Each is named after its path under the notebooks directory,
        `<topic>__<lab>__<file>.<full|short>.ipynb`. With `short`, the
        notebook's one `SHORT_RUN = False` line is set to `True`.

        Returns:
            The queued names.

        Raises:
            GpuRunError: If `short` and a notebook hasn't exactly one \
                `SHORT_RUN = False` line.
        """
        staged = self._dir / "in"
        staged.mkdir(parents=True, exist_ok=True)
        root = self._settings.paths.labs_notebooks_dir.resolve()
        paths = []
        for notebook in notebooks:
            nb = json.loads(notebook.read_text(encoding="utf-8"))
            if short and _set_short_run(nb) != 1:
                msg = f"{notebook}: expected exactly one `SHORT_RUN = False` line"
                raise GpuRunError(msg)
            resolved = notebook.resolve()
            parts = (
                resolved.relative_to(root).parts
                if resolved.is_relative_to(root)
                else (resolved.name,)
            )
            name = "__".join(parts).removesuffix(".ipynb")
            name += ".short.ipynb" if short else ".full.ipynb"
            target = staged / name
            target.write_text(
                json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            paths.append(target)
        self._scp(paths, "/work/in/")
        return [path.name for path in paths]

    def start(self, *, timeout: int = 3 * 3600) -> str:
        """Start the machine's queue, detached; a no-op while it already runs.

        Args:
            timeout: Seconds after which a notebook's run is killed.

        Returns:
            The queue log's last lines.
        """
        scripts = self._dir / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        cpus = self._gpu.cpus
        (scripts / "execute.py").write_text(EXECUTE, encoding="utf-8")
        (scripts / "queue.sh").write_text(
            QUEUE.replace("@TIMEOUT@", str(timeout))
            .replace("@CPUS@", str(cpus))
            .replace("@CPU_LIST@", ",".join(map(str, range(cpus)))),
            encoding="utf-8",
        )
        self._scp([scripts / "execute.py", scripts / "queue.sh"], "/work/")
        return self._ssh(
            "setsid nohup bash /work/queue.sh >> /work/queue.log 2>&1 < /dev/null &"
            " sleep 2; tail -3 /work/queue.log"
        )

    def status(self) -> GpuStatus:
        """The machine's state, and each queued notebook's.

        Returns:
            The status; no queue while the machine isn't running.
        """
        state = self.state()
        if state is None:
            return GpuStatus(instance=None)
        info = self._backend.info(state.id)
        if info is None or info.status != "running" or state.host is None:
            return GpuStatus(instance=info)
        entries = []
        for line in self._ssh(_STATUS).splitlines():
            name, entry_state, done = [*line.split("\t"), "", ""][:3]
            code, seconds = [*done.split(), None, None][:2]
            entries.append(
                QueueEntry(
                    name=name,
                    state=entry_state,
                    exit_code=int(code) if code is not None else None,
                    seconds=int(seconds) if seconds is not None else None,
                )
            )
        return GpuStatus(instance=info, queue=tuple(entries))

    def fetch(self) -> Path:
        """Copy what changed in the machine's executed notebooks to `out/`.

        Returns:
            The local `out/` directory.

        Raises:
            GpuRunError: If rsync fails.
        """
        state = self._connected()
        out = self._dir / "out"
        out.mkdir(parents=True, exist_ok=True)
        ssh = " ".join(["ssh", *self._ssh_options(), "-p", str(state.port)])
        proc = self._run(
            [
                "rsync",
                "-a",
                "--partial",
                "-e",
                ssh,
                f"root@{state.host}:/work/out/",
                f"{out}/",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode:
            msg = f"rsync failed:\n{proc.stderr}"
            raise GpuRunError(msg)
        return out

    def note_finished(self, *, slowest: int = 5) -> list[RunReport]:
        """Append a report of each fetched run not noted yet to `notes.md`.

        So an interrupted session loses nothing: the notes say what ran,
        how long, how much RAM it took, and what raised.

        Returns:
            The newly noted runs.
        """
        out = self._dir / "out"
        noted_file = self._dir / "noted.json"
        noted = (
            set(json.loads(noted_file.read_text(encoding="utf-8")))
            if noted_file.is_file()
            else set()
        )
        new = [
            report(done.with_suffix(""), slowest=slowest)
            for done in sorted(out.glob("*.ipynb.done"))
            if done.with_suffix("").name not in noted and done.with_suffix("").is_file()
        ]
        if not new:
            return []
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
        with (self._dir / "notes.md").open("a", encoding="utf-8") as notes:
            for run in new:
                notes.write(f"\nNoted {stamp}:\n{format_report(run)}\n")
        noted_file.write_text(
            json.dumps(sorted(noted | {run.path.name for run in new})),
            encoding="utf-8",
        )
        return new

    def down(self) -> int | None:
        """Destroy the machine: nothing is billed afterwards.

        Returns:
            The destroyed instance's ID, or None if there was none.
        """
        state = self.state()
        if state is None:
            return None
        self._backend.destroy(state.id)
        self._save(None)
        return state.id


def _set_short_run(nb: dict[str, Any]) -> int:
    found = 0
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        source = cell["source"]
        lines = source if isinstance(source, list) else source.splitlines(True)
        for i, line in enumerate(lines):
            if line.rstrip("\n") == "SHORT_RUN = False":
                lines[i] = line.replace("False", "True")
                found += 1
        cell["source"] = lines
    return found


def _cell_seconds(cell: dict[str, Any]) -> float:
    timing = cell.get("metadata", {}).get("execution", {})
    start, end = timing.get("iopub.execute_input"), timing.get("shell.execute_reply")
    if not (start and end):
        return 0.0
    return (
        datetime.fromisoformat(end.replace("Z", "+00:00"))
        - datetime.fromisoformat(start.replace("Z", "+00:00"))
    ).total_seconds()


def report(path: Path, *, slowest: int = 5) -> RunReport:
    """Read an executed notebook and its `.done`/`.maxrss` files.

    Args:
        path: The executed notebook, as fetched into `out/`.
        slowest: How many of the slowest cells to report.

    Returns:
        Its exit code and run time, peak RAM, the cells that raised, and \
        the slowest cells.
    """
    nb = json.loads(path.read_text(encoding="utf-8"))
    done = path.with_name(path.name + ".done")
    code_seconds = done.read_text(encoding="utf-8").split() if done.is_file() else []
    maxrss = path.with_name(path.name + ".maxrss")
    code = [(i, c) for i, c in enumerate(nb["cells"]) if c["cell_type"] == "code"]
    errors = tuple(
        CellError(i, out.get("ename", ""), out.get("evalue", "")[:200])
        for i, cell in code
        for out in cell.get("outputs", [])
        if out.get("output_type") == "error"
    )
    timings = sorted(
        (
            CellTiming(
                i,
                _cell_seconds(cell),
                ("".join(cell["source"]).strip().splitlines() or [""])[0][:70],
            )
            for i, cell in code
        ),
        key=lambda timing: -timing.seconds,
    )
    return RunReport(
        path=path,
        exit_code=int(code_seconds[0]) if code_seconds else None,
        seconds=int(code_seconds[1]) if len(code_seconds) > 1 else None,
        peak_ram_gib=(
            int(maxrss.read_text(encoding="utf-8")) / 2**20
            if maxrss.is_file()
            else None
        ),
        cells_ran=sum(1 for _, cell in code if cell.get("execution_count")),
        code_cells=len(code),
        errors=errors,
        slowest=tuple(timings[:slowest]),
    )


def format_report(run: RunReport) -> str:
    """A run's report as compact, stable text lines (notes, `--plain`).

    Returns:
        The lines.
    """
    exit_code = "?" if run.exit_code is None else run.exit_code
    seconds = "?" if run.seconds is None else run.seconds
    ram = "?" if run.peak_ram_gib is None else f"{run.peak_ram_gib:.1f} GiB"
    lines = [
        f"#### {run.path.name}: exit {exit_code}, {seconds} s, peak RAM {ram},"
        f" {run.cells_ran}/{run.code_cells} code cells ran"
    ]
    lines += [f"  [{e.index}] raised {e.name}: {e.value}" for e in run.errors]
    lines += [f"  [{t.index}] {t.seconds:7.0f} s  {t.first_line}" for t in run.slowest]
    return "\n".join(lines)
