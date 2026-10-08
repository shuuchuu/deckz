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
plain `ssh`/`scp`/`rsync` to the machine. Several machines can run at once,
each under its own name (`main` by default): a machine's state (ID, address)
lives in `GlobalPaths.labs_gpu_dir/<name>/` (`state.json`), next to its staged
and executed notebooks (`in/`, `out/`) and the notes on its finished runs
(`notes.md`); the machines that failed to boot (`avoid.json`, never rented
again) and the hooks' state (`hooks.json`) are shared.

A notebook's metadata (`labs.gpu.metadata_key`) can ask for `variables` and
`secrets` filled from the environment in the copy sent to the machine (a
secret is redacted from what comes back), and for a `hook`, a command of
`labs.gpu.hooks` run locally before and after its run: see `RunNeeds`.

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
import os
import re
import subprocess
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from logging import getLogger
from pathlib import Path
from shlex import quote
from shutil import which
from typing import TYPE_CHECKING, Any, Protocol

from ..exceptions import GpuRunError, MissingExtraError

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings

_logger = getLogger(__name__)

Runner = Callable[..., subprocess.CompletedProcess[str]]
"""`subprocess.run`'s signature: tests pass a fake one."""

DEFAULT_MACHINE = "main"
_MACHINE_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")

_RESULT_EXTS = (".done", ".log", ".maxrss")
"""What a run leaves next to its executed notebook in `out/`."""

REDACTED = "[deckz: redacted {}]"
"""What a secret's value is replaced with in the fetched files."""

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
  # Each notebook starts from the image's state, as on a fresh Colab VM.
  for dir in @FRESH@; do
    snapshot=/work/pristine/$(echo "${dir#/}" | tr / _)
    [ -e "$snapshot.ok" ] && rsync -a --delete "$snapshot/" "$dir/"
  done
  rm -rf /content && mkdir -p /content && cp "$path" /content/
  (cd /content && PYTHON_CPU_COUNT=@CPUS@ taskset -c @CPU_LIST@ timeout @TIMEOUT@ \\
    python3 /work/execute.py "$name" "/work/out/$name") > "out/$name.log" 2>&1
  echo "$? $(( $(date +%s) - start ))" > "out/$name.done"
  echo "$(date -Is) done $name: $(cat "out/$name.done")"
done
echo "$(date -Is) queue finished"
"""
"""The machine's queue: each staged notebook not run yet, one after the other."""

SNAPSHOT = """\
set -e
mkdir -p /work/pristine
for dir in @FRESH@; do
  snapshot=/work/pristine/$(echo "${dir#/}" | tr / _)
  [ -e "$snapshot.ok" ] && continue
  rsync -a --delete "$dir/" "$snapshot/"
  touch "$snapshot.ok"
done
"""
"""Copies `labs.gpu.fresh_dirs` once, before any notebook runs, for the \
queue to restore before each one."""

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
    machine: str = DEFAULT_MACHINE


@dataclass(frozen=True)
class _Staged:
    name: str
    text: str
    """The copy's JSON, needs filled: secrets in clear."""
    secrets: tuple[str, ...] = ()
    """The environment variables of its secrets."""


@dataclass(frozen=True)
class RunNeeds:
    """What a notebook's runs need, from its metadata (`labs.gpu.metadata_key`).

    `variables` and `secrets` map a variable of the notebook, assigned `""` on
    a line of its own, to the environment variable whose value `queue` puts
    there in the copy it sends; a secret's value is replaced with `REDACTED`
    in the staged copy once sent and in what `fetch` copies back. `hook`
    names a command of `labs.gpu.hooks`.
    """

    variables: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    hook: str | None = None


def run_needs(nb: dict[str, Any], metadata_key: str) -> RunNeeds:
    """Read a notebook's `RunNeeds` from its metadata.

    Returns:
        Them, empty if the notebook has none.
    """
    node: Any = nb.get("metadata", {})
    for part in metadata_key.split("."):
        node = node.get(part, {}) if isinstance(node, dict) else {}
    return RunNeeds(
        variables=dict(node.get("variables", {})),
        secrets=dict(node.get("secrets", {})),
        hook=node.get("hook"),
    )


def machines(settings: "GlobalSettings") -> list[str]:
    """The names of the machines rented, as their `state.json` files say.

    Returns:
        The names, sorted.
    """
    root = settings.paths.labs_gpu_dir
    if not root.is_dir():
        return []
    return sorted(
        path.name for path in root.iterdir() if (path / "state.json").is_file()
    )


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
    """One pass of notebooks on a rented machine, kept in `labs_gpu_dir/<machine>`."""

    def __init__(
        self,
        settings: "GlobalSettings",
        backend: GpuBackend | None = None,
        run: Runner = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        *,
        machine: str = DEFAULT_MACHINE,
    ) -> None:
        if not _MACHINE_NAME.fullmatch(machine):
            msg = f"machine name {machine!r}: use lowercase letters, digits and -"
            raise GpuRunError(msg)
        self._settings = settings
        self._gpu = settings.labs.gpu
        self._root = settings.paths.labs_gpu_dir
        self._dir = self._root / machine
        self.machine = machine
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
        return self._root / "avoid.json"

    @property
    def _hooks_file(self) -> Path:
        return self._root / "hooks.json"

    @property
    def _secrets_file(self) -> Path:
        return self._dir / "secrets.json"

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.is_file():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=1), encoding="utf-8")

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
            self._write_json(self._avoid_file, [*self._avoided(), state.machine])
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
        gpu = self._ssh(
            "nvidia-smi -L; mkdir -p /work/in /work/out; python3 -c 'import nbclient'"
        )
        if self._gpu.fresh_dirs:
            _logger.info("Snapshotting %s", ", ".join(self._gpu.fresh_dirs))
            self._ssh(SNAPSHOT.replace("@FRESH@", self._fresh_dirs()))
        return gpu

    def _fresh_dirs(self) -> str:
        return " ".join(quote(path.rstrip("/")) for path in self._gpu.fresh_dirs)

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

    def queue(
        self, notebooks: Sequence[Path], *, short: bool = False
    ) -> tuple[list[str], list[Path]]:
        """Stage notebooks and send them to the machine's queue.

        Each is named after its path under the notebooks directory,
        `<topic>__<lab>__<file>.<full|short>.ipynb`. With `short`, the
        notebook's one `SHORT_RUN = False` line is set to `True`. Its
        `RunNeeds` are met: variables and secrets filled from the
        environment, and its hook run first, unless a run naming the same
        hook isn't done yet: the notebook is then held, and sent once that
        run's closing hook ran (see `finish_hooks`).

        Returns:
            The queued names, and the notebooks held.

        Raises:
            GpuRunError: If `short` and a notebook hasn't exactly one \
                `SHORT_RUN = False` line, if a variable or secret can't be \
                filled, or if a hook is unknown or fails.
        """
        queued: list[str] = []
        held: list[Path] = []
        for notebook in notebooks:
            nb = json.loads(notebook.read_text(encoding="utf-8"))
            needs = run_needs(nb, self._gpu.metadata_key)
            if needs.hook is None:
                queued.append(self._send(self._stage(notebook, nb, needs, short)))
                continue
            if needs.hook not in self._gpu.hooks:
                msg = f"{notebook}: hook {needs.hook!r} is not in labs.gpu.hooks"
                raise GpuRunError(msg)
            hooks = self._read_json(self._hooks_file, {})
            entry = hooks.setdefault(needs.hook, {"active": None, "waiting": []})
            if entry["active"] is not None or entry["waiting"]:
                entry["waiting"].append(
                    {
                        "machine": self.machine,
                        "notebook": str(notebook.resolve()),
                        "short": short,
                    }
                )
                self._write_json(self._hooks_file, hooks)
                held.append(notebook)
                continue
            staged = self._stage(notebook, nb, needs, short)
            self._run_hook(needs.hook)
            name = self._send(staged)
            entry["active"] = {"machine": self.machine, "name": name}
            self._write_json(self._hooks_file, hooks)
            queued.append(name)
        return queued, held

    def _stage(
        self, notebook: Path, nb: dict[str, Any], needs: RunNeeds, short: bool
    ) -> "_Staged":
        """Prepare one notebook's copy for the machine, its needs filled.

        Returns:
            The copy, not written yet.

        Raises:
            GpuRunError: If it can't be prepared as asked.
        """
        if short and _set_short_run(nb) != 1:
            msg = f"{notebook}: expected exactly one `SHORT_RUN = False` line"
            raise GpuRunError(msg)
        filled = {**needs.variables, **needs.secrets}
        unset = sorted(env for env in filled.values() if not os.environ.get(env))
        if unset:
            msg = f"{notebook}: set {', '.join(unset)} (in the environment or .env)"
            raise GpuRunError(msg)
        unfilled = _fill_variables(
            nb, {variable: os.environ[env] for variable, env in filled.items()}
        )
        if unfilled:
            lines = ", ".join(f'`{variable} = ""`' for variable in unfilled)
            msg = f"{notebook}: expected exactly one line {lines}"
            raise GpuRunError(msg)
        root = self._settings.paths.labs_notebooks_dir.resolve()
        resolved = notebook.resolve()
        parts = (
            resolved.relative_to(root).parts
            if resolved.is_relative_to(root)
            else (resolved.name,)
        )
        name = "__".join(parts).removesuffix(".ipynb")
        name += ".short.ipynb" if short else ".full.ipynb"
        return _Staged(
            name=name,
            text=json.dumps(nb, ensure_ascii=False, indent=1),
            secrets=tuple(sorted(needs.secrets.values())),
        )

    def _send(self, staged: "_Staged") -> str:
        """Write a staged copy to `in/` and copy it to the machine.

        A copy with secrets is redacted once sent, so they never stay on
        disk here, and its name noted for `fetch` to redact its results. A
        name queued before runs again: its earlier results are removed, on
        the machine (once the new copy is there, so the queue never runs the
        old one) and here.

        Returns:
            Its queued name.
        """
        target = self._dir / "in" / staged.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(staged.text, encoding="utf-8")
        try:
            self._scp([target], "/work/in/")
        finally:
            if staged.secrets:
                target.write_text(
                    _redact(staged.text, staged.secrets), encoding="utf-8"
                )
                secrets = self._read_json(self._secrets_file, {})
                secrets[staged.name] = list(staged.secrets)
                self._write_json(self._secrets_file, secrets)
        results = [staged.name, *(f"{staged.name}{ext}" for ext in _RESULT_EXTS)]
        self._ssh("cd /work/out 2>/dev/null && rm -f " + " ".join(map(quote, results)))
        for result in results:
            (self._dir / "out" / result).unlink(missing_ok=True)
        noted_file = self._dir / "noted.json"
        noted = self._read_json(noted_file, [])
        if staged.name in noted:
            self._write_json(
                noted_file, [name for name in noted if name != staged.name]
            )
        return staged.name

    def send_held(self, notebook: Path, *, short: bool) -> str:
        """Send a notebook held for its hook, its hook already run.

        Returns:
            Its queued name.
        """
        nb = json.loads(notebook.read_text(encoding="utf-8"))
        needs = run_needs(nb, self._gpu.metadata_key)
        return self._send(self._stage(notebook, nb, needs, short))

    # -- hooks ----------------------------------------------------------------

    def _run_hook(self, hook: str) -> None:
        command = self._gpu.hooks[hook]
        _logger.info("Running hook %s: %s", hook, command)
        proc = self._run(
            ["sh", "-c", command],
            cwd=self._settings.paths.git_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        for line in (proc.stdout or "").splitlines():
            _logger.info("%s: %s", hook, line)
        if proc.returncode:
            msg = (
                f"hook {hook} failed ({proc.returncode}): {command}\n"
                f"{proc.stdout or ''}{proc.stderr or ''}"
            )
            raise GpuRunError(msg)

    def hooks_pending(self) -> bool:
        """Whether a hooked run of this machine isn't closed, or one is held.

        Returns:
            True while `finish_hooks` still has something to do here.
        """
        for entry in self._read_json(self._hooks_file, {}).values():
            active = entry["active"]
            if active is not None and active["machine"] == self.machine:
                return True
            if any(held["machine"] == self.machine for held in entry["waiting"]):
                return True
        return False

    def finish_hooks(self, *, machine_down: bool = False) -> list[str]:
        """Close this machine's finished hooked runs, then send the held ones.

        A hooked run is finished once its `.done` file was fetched, or when
        its machine is down: its hook then runs again. Then the first
        notebook held for each hook with no run is sent to its own machine,
        the hook run first unless it just ran. With `machine_down`, the
        notebooks held for this machine are dropped.

        Returns:
            What was done, one line each.
        """
        hooks = self._read_json(self._hooks_file, {})
        done: list[str] = []
        for hook, entry in hooks.items():
            if machine_down:
                dropped = [h for h in entry["waiting"] if h["machine"] == self.machine]
                done += [f"dropped {h['notebook']}: machine down" for h in dropped]
                entry["waiting"] = [h for h in entry["waiting"] if h not in dropped]
                self._write_json(self._hooks_file, hooks)
            active = entry["active"]
            just_ran = False
            if active is not None and active["machine"] == self.machine:
                finished = (self._dir / "out" / f"{active['name']}.done").is_file()
                if finished or machine_down:
                    self._run_hook(hook)
                    just_ran = True
                    entry["active"] = None
                    self._write_json(self._hooks_file, hooks)
                    done.append(f"ran hook {hook} after {active['name']}")
            if entry["active"] is None and entry["waiting"]:
                held = entry["waiting"][0]
                target = (
                    self
                    if held["machine"] == self.machine
                    else GpuRun(
                        self._settings,
                        self._backend,
                        self._run,
                        self._sleep,
                        machine=held["machine"],
                    )
                )
                if not just_ran:
                    self._run_hook(hook)
                name = target.send_held(Path(held["notebook"]), short=held["short"])
                entry["waiting"].pop(0)
                entry["active"] = {"machine": target.machine, "name": name}
                self._write_json(self._hooks_file, hooks)
                target.ensure_running()
                done.append(f"queued {name} on {target.machine}")
        for line in done:
            _logger.info("%s", line)
        return done

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
        (scripts / "execute.py.new").write_text(EXECUTE, encoding="utf-8")
        (scripts / "queue.sh.new").write_text(
            QUEUE.replace("@TIMEOUT@", str(timeout))
            .replace("@CPUS@", str(cpus))
            .replace("@CPU_LIST@", ",".join(map(str, range(cpus))))
            .replace("@FRESH@", self._fresh_dirs()),
            encoding="utf-8",
        )
        self._write_json(self._dir / "queue.json", {"timeout": timeout})
        self._scp([scripts / "execute.py.new", scripts / "queue.sh.new"], "/work/")
        # Renamed into place: a queue running keeps reading its own script.
        return self._ssh(
            "cd /work && mv -f execute.py.new execute.py && mv -f queue.sh.new"
            " queue.sh && (setsid nohup bash /work/queue.sh >> /work/queue.log 2>&1"
            " < /dev/null &) && sleep 2 && tail -3 /work/queue.log"
        )

    def ensure_running(self) -> str:
        """Start the queue again, with its last timeout, unless it runs.

        Returns:
            The queue log's last lines.
        """
        timeout = self._read_json(self._dir / "queue.json", {}).get("timeout")
        return self.start(timeout=timeout or 3 * 3600)

    def status(self) -> GpuStatus:
        """The machine's state, and each queued notebook's.

        Returns:
            The status; no queue while the machine isn't running.
        """
        state = self.state()
        if state is None:
            return GpuStatus(instance=None, machine=self.machine)
        info = self._backend.info(state.id)
        if info is None or info.status != "running" or state.host is None:
            return GpuStatus(instance=info, machine=self.machine)
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
        return GpuStatus(instance=info, queue=tuple(entries), machine=self.machine)

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
        for name, envs in self._read_json(self._secrets_file, {}).items():
            for path in (out / name, out / f"{name}.log"):
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8", errors="surrogateescape")
                redacted = _redact(text, envs)
                if redacted != text:
                    path.write_text(
                        redacted, encoding="utf-8", errors="surrogateescape"
                    )
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
        self.finish_hooks(machine_down=True)
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


def _fill_variables(nb: dict[str, Any], values: dict[str, str]) -> list[str]:
    """Set each `name = ""` line of `nb`'s code cells to `values[name]`.

    Returns:
        The names whose line wasn't found exactly once.
    """
    found = dict.fromkeys(values, 0)
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        source = cell["source"]
        lines = source if isinstance(source, list) else source.splitlines(True)
        for i, line in enumerate(lines):
            for name, value in values.items():
                if line.strip() == f'{name} = ""':
                    indent = line[: len(line) - len(line.lstrip())]
                    newline = "\n" if line.endswith("\n") else ""
                    lines[i] = f"{indent}{name} = {json.dumps(value)}{newline}"
                    found[name] += 1
        cell["source"] = lines
    return [name for name, count in found.items() if count != 1]


def _redact(text: str, envs: Sequence[str]) -> str:
    """Replace the values of the environment variables `envs` in `text`.

    Both as is and as escaped in a JSON string.

    Returns:
        The redacted text.

    Raises:
        GpuRunError: If one of `envs` isn't set: its value can't be found.
    """
    for env in envs:
        value = os.environ.get(env)
        if not value:
            msg = f"set {env} to redact its value from the fetched notebooks"
            raise GpuRunError(msg)
        escaped = json.dumps(value, ensure_ascii=False)[1:-1]
        for form in sorted({value, escaped}, key=len, reverse=True):
            text = text.replace(form, REDACTED.format(env))
    return text


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
