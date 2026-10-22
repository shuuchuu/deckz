import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from pygit2 import init_repository
from pytest import (
    CaptureFixture,
    LogCaptureFixture,
    MonkeyPatch,
    approx,
    fixture,
    raises,
)

from deckz.cli import main
from deckz.configuring.settings import (
    GlobalPaths,
    GlobalSettings,
    LabsGpuSettings,
    LabsOutputsHook,
    LabsOutputsSettings,
    LabsSettings,
)
from deckz.exceptions import GpuRunError, MissingExtraError
from deckz.labs import gpu_pass
from deckz.labs.gpu import (
    IDLE_CPUS,
    QUEUE,
    STOP_SIGNALS,
    GpuRun,
    GpuStatus,
    InstanceInfo,
    Offer,
    QueueEntry,
    VastBackend,
    format_report,
    machines,
    report,
    uninterrupted,
)

_OFFER = {
    "id": 7,
    "gpu_name": "Tesla T4",
    "machine_id": 42,
    "dph_total": 0.16,
    "geolocation": "FR",
}


def _running(port: int = 40100) -> dict[str, Any]:
    return {
        "actual_status": "running",
        "cur_state": "running",
        "public_ipaddr": "203.0.113.5 ",
        "ports": {"22/tcp": [{"HostPort": str(port)}]},
        "gpu_name": "Tesla T4",
        "dph_total": 0.16,
    }


class FakeRunner:
    """Stands in for `subprocess.run`: the vastai CLI, ssh, scp, rsync."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.instances: list[dict[str, Any] | None] = []
        self.contracts = iter(range(100, 200))
        self.ssh_output = ""
        # How many `ssh ... true` readiness checks refuse the key first.
        self.ssh_refusals = 0

    def __call__(self, args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        out = ""
        if args[:3] == ["vastai", "search", "offers"]:
            out = json.dumps([_OFFER])
        elif args[:3] == ["vastai", "create", "instance"]:
            out = json.dumps({"success": True, "new_contract": next(self.contracts)})
        elif args[:3] == ["vastai", "show", "instance"]:
            # Each poll sees the next state; the last one stays.
            if len(self.instances) > 1:
                current = self.instances.pop(0)
            else:
                current = self.instances[0] if self.instances else None
            out = json.dumps(current) if current is not None else ""
        elif args[0] == "ssh":
            if args[-1] == "true" and self.ssh_refusals:
                self.ssh_refusals -= 1
                return subprocess.CompletedProcess(args, 255, "", "Permission denied")
            out = self.ssh_output
        return subprocess.CompletedProcess(args, 0, out, "")

    def commands(self, program: str) -> list[list[str]]:
        return [call for call in self.calls if call[0] == program]


@fixture
def repo(tmp_path: Path) -> Path:
    init_repository(str(tmp_path))
    return tmp_path


def _settings(repo: Path, hooks: dict[str, str] | None = None) -> GlobalSettings:
    return GlobalSettings(
        paths=GlobalPaths(current_dir=repo, git_dir=repo),
        labs=LabsSettings(gpu=LabsGpuSettings(hooks=hooks or {})),
    )


def _no_sleep(_: float) -> None:
    pass


def _gpu_run(
    repo: Path,
    runner: FakeRunner,
    machine: str = "main",
    hooks: dict[str, str] | None = None,
) -> GpuRun:
    settings = _settings(repo, hooks)
    return GpuRun(
        settings,
        VastBackend(settings, runner),
        run=runner,
        sleep=_no_sleep,
        machine=machine,
    )


def test_up_rents_boots_and_records_the_ssh_address(repo: Path) -> None:
    runner = FakeRunner()
    runner.instances = [_running()]
    runner.ssh_output = "GPU 0: Tesla T4"
    gpu_run = _gpu_run(repo, runner)

    assert gpu_run.up() == "GPU 0: Tesla T4"

    state = gpu_run.state()
    assert state is not None
    assert (state.id, state.machine, state.host, state.port) == (
        100,
        42,
        "203.0.113.5",
        40100,
    )
    assert state.price == approx(0.16)  # The offer's: it bills at that rate.
    create = runner.commands("vastai")[1]
    assert create[create.index("--image") + 1] == _settings(repo).labs.gpu.image


def test_up_avoids_a_machine_that_failed_to_boot(repo: Path) -> None:
    runner = FakeRunner()
    runner.instances = [
        {"actual_status": "exited", "cur_state": "stopped", "status_msg": "pull"},
        _running(),
    ]
    gpu_run = _gpu_run(repo, runner)

    gpu_run.up()

    vastai = runner.commands("vastai")
    assert ["vastai", "destroy", "instance", "100", "-y"] in vastai
    searches = [call for call in vastai if call[1] == "search"]
    assert "machine_id!=42" not in searches[0][3]
    assert "machine_id!=42" in searches[1][3]
    assert json.loads((gpu_run.directory.parent / "avoid.json").read_text()) == [42]
    state = gpu_run.state()
    assert state is not None
    assert state.id == 101


def test_up_avoids_a_machine_that_never_accepts_ssh(repo: Path) -> None:
    runner = FakeRunner()
    runner.instances = [_running()]
    runner.ssh_refusals = 20  # Every readiness check of the first machine.
    runner.ssh_output = "GPU 0: Tesla T4"
    gpu_run = _gpu_run(repo, runner)

    assert gpu_run.up() == "GPU 0: Tesla T4"

    vastai = runner.commands("vastai")
    assert ["vastai", "destroy", "instance", "100", "-y"] in vastai
    searches = [call for call in vastai if call[1] == "search"]
    assert "machine_id!=42" in searches[1][3]
    assert json.loads((gpu_run.directory.parent / "avoid.json").read_text()) == [42]
    state = gpu_run.state()
    assert state is not None
    assert state.id == 101


def test_queue_stages_named_notebooks_and_short_flips_short_run(repo: Path) -> None:
    runner = FakeRunner()
    runner.instances = [_running()]
    gpu_run = _gpu_run(repo, runner)
    gpu_run.up()
    notebook = repo / "labs" / "notebooks" / "nn" / "cnn" / "demo-fr.ipynb"
    notebook.parent.mkdir(parents=True)
    cell = {"cell_type": "code", "source": ["SHORT_RUN = False\n"], "metadata": {}}
    notebook.write_text(json.dumps({"cells": [cell], "metadata": {}}))

    names, held = gpu_run.queue([notebook], short=True)

    assert (names, held) == (["nn__cnn__demo-fr.short.ipynb"], [])
    staged = json.loads((gpu_run.directory / "in" / names[0]).read_text())
    assert staged["cells"][0]["source"] == ["SHORT_RUN = True\n"]
    assert runner.commands("scp")[-1][-1].endswith(":/work/in/")


def test_queue_short_refuses_a_notebook_without_short_run(repo: Path) -> None:
    runner = FakeRunner()
    runner.instances = [_running()]
    gpu_run = _gpu_run(repo, runner)
    gpu_run.up()
    notebook = repo / "demo-fr.ipynb"
    notebook.write_text(json.dumps({"cells": [], "metadata": {}}))

    with raises(GpuRunError):
        gpu_run.queue([notebook], short=True)


def test_start_pins_the_cpus_and_sets_the_timeout(repo: Path) -> None:
    runner = FakeRunner()
    runner.instances = [_running()]
    gpu_run = _gpu_run(repo, runner)
    gpu_run.up()

    gpu_run.start(timeout=600)

    queue = (gpu_run.directory / "scripts" / "queue.sh.new").read_text()
    assert 'PYTHON_CPU_COUNT=2 taskset -c "$cpu_list" timeout 600' in queue
    assert 'DECKZ_GPU_RUN="$run_tag" LLAMA_ARG_THREADS=2' in queue
    # The least busy CPUs, picked before each notebook, else the first ones.
    assert "cpu_list=$(python3 - 2 <<'PICK'\n" + IDLE_CPUS.rstrip("\n") in queue
    assert '[ -n "$cpu_list" ] || cpu_list=0,1' in queue
    assert "for dir in /usr/local; do" in queue
    assert "CONTAINER_*|VAST_*" in queue
    assert "@" not in queue
    assert json.loads((gpu_run.directory / "queue.json").read_text()) == {
        "timeout": 600
    }
    # The scripts are renamed into place, never rewritten under a running queue.
    assert runner.commands("ssh")[-1][-1].startswith(
        "cd /work && mv -f execute.py.new execute.py && mv -f queue.sh.new queue.sh"
    )


def test_idle_cpus_picks_the_least_busy_allowed_cpus() -> None:
    namespace: dict[str, Any] = {}
    exec(IDLE_CPUS, namespace)
    pick = namespace["pick"]
    # (all ticks, idle ticks): over the interval, CPUs 0 and 1 stay busy, 2 and 3
    # are idle, 4 is idle but not allowed, 5 lies outside /proc/stat's second read.
    before = {0: (0, 0), 1: (0, 0), 2: (0, 0), 3: (0, 0), 4: (0, 0), 5: (0, 0)}
    after = {0: (100, 0), 1: (100, 5), 2: (100, 90), 3: (100, 99), 4: (100, 100)}

    assert pick(before, after, {0, 1, 2, 3, 5}, 2) == [2, 3]
    assert pick(before, after, {0, 1, 2, 3, 5}, 3) == [1, 2, 3]
    # A CPU with no ticks counts as busy.
    assert pick({0: (5, 5), 1: (0, 0)}, {0: (5, 5), 1: (10, 10)}, {0, 1}, 1) == [1]


def test_idle_cpus_runs_as_the_queue_runs_it() -> None:
    result = subprocess.run(
        ["python3", "-", "2"],
        input=IDLE_CPUS,
        capture_output=True,
        text=True,
        check=True,
    )

    cpus = [int(cpu) for cpu in result.stdout.strip().split(",")]
    assert len(cpus) == min(2, len(os.sched_getaffinity(0)))
    assert set(cpus) <= os.sched_getaffinity(0)


def test_queue_kills_what_a_run_leaves_running(tmp_path: Path) -> None:
    start = QUEUE.index("  for environ in")
    cleanup = QUEUE[start : QUEUE.index("  done\n", start) + len("  done\n")]
    pids = tmp_path / "pids"
    # A server the run started, detached as `ollama serve &` would be, and a
    # process of someone else's on the machine.
    spawn = (
        f"DECKZ_GPU_RUN=nb.ipynb.1 setsid sleep 300 & echo $! >> {pids}\n"
        f"DECKZ_GPU_RUN=other.ipynb.1 setsid sleep 300 & echo $! >> {pids}\n"
    )
    subprocess.run(["bash", "-c", spawn], check=True)
    left, other = map(int, pids.read_text().split())
    try:
        _wait_for_env(left, b"DECKZ_GPU_RUN=nb.ipynb.1")
        _wait_for_env(other, b"DECKZ_GPU_RUN=other.ipynb.1")
        result = subprocess.run(
            ["bash", "-c", "name=nb.ipynb\nrun_tag=nb.ipynb.1\n" + cleanup],
            capture_output=True,
            text=True,
            check=True,
        )

        assert f"killed {left} left by nb.ipynb" in result.stdout
        _wait_gone(left)
        assert Path(f"/proc/{other}").exists()
    finally:
        for pid in (left, other):
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)


def _wait_for_env(pid: int, entry: bytes) -> None:
    # A forked child's environ holds its new variables only once it has exec'd.
    for _ in range(500):
        if entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
            return
        time.sleep(0.01)
    msg = f"{pid} never got {entry!r}"
    raise AssertionError(msg)


def _wait_gone(pid: int) -> None:
    # `kill -9` returns before the process exits: on a loaded machine it can
    # still be running a moment later.
    for _ in range(500):
        if not Path(f"/proc/{pid}").exists() or _zombie(pid):
            return
        time.sleep(0.01)
    msg = f"{pid} still running after kill -9"
    raise AssertionError(msg)


def _zombie(pid: int) -> bool:
    # Gone between the caller's `exists()` and this read counts too.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return True
    return stat.split(") ")[1].startswith("Z")


def test_status_parses_the_machine_queue(repo: Path) -> None:
    runner = FakeRunner()
    runner.instances = [_running()]
    gpu_run = _gpu_run(repo, runner)
    gpu_run.up()
    runner.ssh_output = "a.full.ipynb\tdone\t0 83\nb.full.ipynb\trunning\t\n"

    current = gpu_run.status()

    assert current.instance is not None
    assert [(e.name, e.state, e.exit_code, e.seconds) for e in current.queue] == [
        ("a.full.ipynb", "done", 0, 83),
        ("b.full.ipynb", "running", None, None),
    ]


def test_commands_needing_a_machine_refuse_without_one(repo: Path) -> None:
    with raises(GpuRunError):
        _gpu_run(repo, FakeRunner()).fetch()


def test_up_snapshots_the_fresh_dirs_before_any_run(repo: Path) -> None:
    runner = FakeRunner()
    runner.instances = [_running()]

    _gpu_run(repo, runner).up()

    snapshot = runner.commands("ssh")[-1][-1]
    assert "for dir in /usr/local; do" in snapshot
    assert 'rsync -a --delete "$dir/" "$snapshot/"' in snapshot


def test_up_snapshots_nothing_without_fresh_dirs(repo: Path) -> None:
    runner = FakeRunner()
    runner.instances = [_running()]
    settings = GlobalSettings(
        paths=GlobalPaths(current_dir=repo, git_dir=repo),
        labs=LabsSettings(gpu=LabsGpuSettings(fresh_dirs=())),
    )

    GpuRun(settings, VastBackend(settings, runner), run=runner, sleep=_no_sleep).up()

    assert not any("pristine" in call[-1] for call in runner.commands("ssh"))


def test_down_destroys_and_forgets_the_machine(repo: Path) -> None:
    runner = FakeRunner()
    runner.instances = [_running()]
    gpu_run = _gpu_run(repo, runner)
    gpu_run.up()

    assert gpu_run.down() == 100
    assert gpu_run.state() is None
    assert gpu_run.down() is None
    assert not (gpu_run.directory.parent / "avoid.json").exists()  # It booted.


def test_down_avoids_a_machine_that_never_finished_booting(
    repo: Path, caplog: LogCaptureFixture
) -> None:
    # Destroyed by hand while stuck "loading": never rented again.
    runner = FakeRunner()
    gpu_run = _gpu_run(repo, runner)
    gpu_run.directory.mkdir(parents=True)
    (gpu_run.directory / "state.json").write_text(
        json.dumps({"id": 100, "gpu": "RTX A5000", "machine": 42})
    )

    assert gpu_run.down() == 100

    assert json.loads((gpu_run.directory.parent / "avoid.json").read_text()) == [42]
    assert "machine 42 avoided from now on" in caplog.text
    runner.instances = [_running()]
    runner.ssh_output = "GPU 0: Tesla T4"
    gpu_run.up()
    searches = [c for c in runner.commands("vastai") if c[1] == "search"]
    assert "machine_id!=42" in searches[-1][3]


class ScriptedRunner(FakeRunner):
    """vastai answers as scripted: `searches` by GPU, `creates` in turn."""

    def __init__(
        self,
        searches: dict[str, tuple[str, str]],
        creates: list[tuple[str, str]] | None = None,
    ) -> None:
        super().__init__()
        self.searches = searches
        self.creates = creates or []

    def __call__(
        self, args: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if args[:3] == ["vastai", "search", "offers"]:
            self.calls.append(list(args))
            gpu = args[3].split()[0].removeprefix("gpu_name=")
            return subprocess.CompletedProcess(args, 0, *self.searches[gpu])
        if args[:3] == ["vastai", "create", "instance"] and self.creates:
            self.calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, *self.creates.pop(0))
        return super().__call__(args, **kwargs)


def test_rent_says_why_no_offer_was_rented(repo: Path) -> None:
    # Tesla_T4: nothing matches (another pass just rented the only one, say);
    # RTX_A4000: both offers taken meanwhile.
    offers = [_OFFER | {"id": 8, "gpu_name": "RTX A4000"}, _OFFER | {"id": 9}]
    gone = json.dumps({"success": False, "error": "no_such_ask", "msg": "gone"})
    runner = ScriptedRunner(
        {"Tesla_T4": ("[]", ""), "RTX_A4000": (json.dumps(offers), "")},
        creates=[(gone, ""), ("", '{"error": true, "status_code": 429}')],
    )
    backend = VastBackend(_settings(repo), runner)

    with raises(GpuRunError) as error:
        backend.rent(("Tesla_T4", "RTX_A4000"), avoid=[5])

    message = str(error.value)
    assert message.startswith("no offer rented among Tesla_T4, RTX_A4000: ")
    assert "Tesla_T4: no offer matches `labs.gpu.offer_filter`" in message
    assert (
        'RTX_A4000: offer 8 (gone), offer 9 ({"error": true, "status_code": 429})'
        " refused"
    ) in message
    assert "1 machine(s) avoided" in message
    assert "--dry-run" in message


def test_rent_tries_the_next_offers_before_the_next_gpu(repo: Path) -> None:
    offers = [_OFFER | {"id": i} for i in range(1, 8)]
    gone = (json.dumps({"success": False, "msg": "gone"}), "")
    runner = ScriptedRunner(
        {"Tesla_T4": (json.dumps(offers), "")}, creates=[gone, gone, gone]
    )

    state = VastBackend(_settings(repo), runner).rent(("Tesla_T4",), avoid=[])

    created = [call[3] for call in runner.commands("vastai") if call[1] == "create"]
    assert created == ["1", "2", "3", "4"]
    assert state.id == 100


def test_offers_reports_a_failed_search(repo: Path) -> None:
    # vastai exits 0 on an HTTP error, its error on stderr, stdout empty.
    error = '{"error": true, "status_code": 429, "msg": "slow down"}'
    runner = ScriptedRunner({"Tesla_T4": ("", error)})

    with raises(GpuRunError, match=r"search offers failed:\n.*slow down"):
        VastBackend(_settings(repo), runner).offers("Tesla_T4", avoid=[])


def test_uninterrupted_holds_the_stop_signals_and_nests() -> None:
    def blocked() -> set[int]:
        return set(signal.pthread_sigmask(signal.SIG_BLOCK, []))

    before = blocked()
    with uninterrupted():
        with uninterrupted():
            assert blocked() >= STOP_SIGNALS
        assert blocked() >= STOP_SIGNALS  # The inner block kept them held.
    assert blocked() == before


def test_uninterrupted_delivers_a_signal_once_the_block_is_done() -> None:
    received: list[int] = []
    previous = signal.signal(signal.SIGTERM, lambda signum, _: received.append(signum))
    try:
        with uninterrupted():
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(0.1)
            assert received == []
        time.sleep(0.1)
        assert received == [signal.SIGTERM]
    finally:
        signal.signal(signal.SIGTERM, previous)


def _executed(out: Path, name: str = "nn__demo-fr.full.ipynb") -> Path:
    out.mkdir(parents=True, exist_ok=True)
    cells = [
        {
            "cell_type": "code",
            "execution_count": 1,
            "source": ["model.fit(x)\n"],
            "metadata": {
                "execution": {
                    "iopub.execute_input": "2026-10-07T10:00:00Z",
                    "shell.execute_reply": "2026-10-07T10:01:30Z",
                }
            },
            "outputs": [],
        },
        {
            "cell_type": "code",
            "execution_count": 2,
            "source": ["1 / 0"],
            "metadata": {},
            "outputs": [
                {"output_type": "error", "ename": "ZeroDivisionError", "evalue": "x"}
            ],
        },
        {"cell_type": "code", "source": ["never()"], "metadata": {}, "outputs": []},
    ]
    path = out / name
    path.write_text(json.dumps({"cells": cells, "metadata": {}}))
    (out / f"{name}.done").write_text("0 95\n")
    (out / f"{name}.maxrss").write_text(str(13 * 2**20))
    return path


def test_report_reads_exit_time_ram_errors_and_slowest_cells(tmp_path: Path) -> None:
    run = report(_executed(tmp_path))

    assert (run.exit_code, run.seconds, run.peak_ram_gib) == (0, 95, 13.0)
    assert (run.cells_ran, run.code_cells) == (2, 3)
    assert [(e.index, e.name) for e in run.errors] == [(1, "ZeroDivisionError")]
    assert run.slowest[0].index == 0
    assert run.slowest[0].seconds == 90
    assert format_report(run).splitlines()[0] == (
        "#### nn__demo-fr.full.ipynb: exit 0, 95 s, peak RAM 13.0 GiB,"
        " 2/3 code cells ran"
    )
    assert run.shell_failures == ()


def test_report_reads_the_failed_shell_commands(tmp_path: Path) -> None:
    path = _executed(tmp_path)
    path.with_name(path.name + ".shell").write_text(
        '[0, 127, "nvidia-smi"]\n[1, 1, "pip install nothing"]\n'
    )

    run = report(path)

    assert [(s.index, s.exit_code, s.command) for s in run.shell_failures] == [
        (0, 127, "nvidia-smi"),
        (1, 1, "pip install nothing"),
    ]
    assert format_report(run).splitlines()[2:4] == [
        "  [0] shell command exited with code 127: nvidia-smi",
        "  [1] shell command exited with code 1: pip install nothing",
    ]


def test_note_finished_notes_each_run_once(repo: Path) -> None:
    gpu_run = _gpu_run(repo, FakeRunner())
    _executed(gpu_run.directory / "out")

    assert [run.path.name for run in gpu_run.note_finished()] == [
        "nn__demo-fr.full.ipynb"
    ]
    assert gpu_run.note_finished() == []
    notes = (gpu_run.directory / "notes.md").read_text()
    assert notes.count("#### nn__demo-fr.full.ipynb") == 1


def test_vast_backend_needs_the_vastai_cli(
    repo: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr("deckz.labs.gpu.which", lambda _: None)

    with raises(MissingExtraError):
        VastBackend(_settings(repo)).destroy(1)


def test_cli_report_plain(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    import appdirs

    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(repo))
    monkeypatch.chdir(repo)
    _executed(repo / ".run" / "gpu" / "main" / "out")

    main(("labs", "gpu", "report", "--plain"))

    out = capsys.readouterr().out
    assert out.startswith("#### nn__demo-fr.full.ipynb: exit 0, 95 s")
    assert "[1] raised ZeroDivisionError" in out


def _notebook(path: Path, gpu: dict[str, Any], source: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cell = {"cell_type": "code", "source": source, "metadata": {}, "outputs": []}
    path.write_text(
        json.dumps({"cells": [cell], "metadata": {"shuuchuu": {"gpu": gpu}}})
    )
    return path


def _up(repo: Path, runner: FakeRunner, machine: str, **kwargs: Any) -> GpuRun:
    runner.instances = [_running()]
    gpu_run = _gpu_run(repo, runner, machine, **kwargs)
    gpu_run.up()
    return gpu_run


def test_machines_keep_their_own_state(repo: Path) -> None:
    runner = FakeRunner()
    first = _up(repo, runner, "light")
    second = _up(repo, runner, "heavy")

    assert machines(_settings(repo)) == ["heavy", "light"]
    first_state, second_state = first.state(), second.state()
    assert first_state is not None
    assert second_state is not None
    assert (first_state.id, second_state.id) == (100, 101)
    assert first.directory.name == "light"
    with raises(GpuRunError):
        _gpu_run(repo, runner, "Not a name")


def test_queue_fills_variables_and_secrets_and_redacts_the_staged_copy(
    repo: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_USER", "jeanne")
    monkeypatch.setenv("LAB_TOKEN", "s3cr3t-t0ken")
    runner = FakeRunner()
    gpu_run = _up(repo, runner, "main")
    notebook = _notebook(
        repo / "demo-fr.ipynb",
        {"variables": {"username": "LAB_USER"}, "secrets": {"token": "LAB_TOKEN"}},
        ['username = ""\n', '  token = ""\n', "print(token)"],
    )
    sent: list[str] = []

    def scp_reads_the_copy(args: list[str], **kwargs: Any) -> Any:
        if args[0] == "scp":
            sent.append(Path(args[-2]).read_text())
        return runner(args, **kwargs)

    gpu_run = GpuRun(
        _settings(repo),
        VastBackend(_settings(repo), runner),
        run=scp_reads_the_copy,
        sleep=_no_sleep,
    )
    (name,), _ = gpu_run.queue([notebook])

    assert json.loads(sent[0])["cells"][0]["source"] == [
        'username = "jeanne"\n',
        '  token = "s3cr3t-t0ken"\n',
        "print(token)",
    ]
    staged = (gpu_run.directory / "in" / name).read_text()
    assert "s3cr3t-t0ken" not in staged
    assert "[deckz: redacted LAB_TOKEN]" in staged
    assert "jeanne" in staged


def test_queue_refuses_an_unset_variable_before_sending(
    repo: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.delenv("LAB_TOKEN", raising=False)
    runner = FakeRunner()
    gpu_run = _up(repo, runner, "main")
    notebook = _notebook(
        repo / "demo-fr.ipynb", {"secrets": {"token": "LAB_TOKEN"}}, ['token = ""']
    )

    with raises(GpuRunError, match="LAB_TOKEN"):
        gpu_run.queue([notebook])
    assert runner.commands("scp") == []


def test_fetch_redacts_the_secrets_of_the_executed_copies(
    repo: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_TOKEN", "s3cr3t-t0ken")
    runner = FakeRunner()
    gpu_run = _up(repo, runner, "main")
    notebook = _notebook(
        repo / "demo-fr.ipynb", {"secrets": {"token": "LAB_TOKEN"}}, ['token = ""']
    )
    (name,), _ = gpu_run.queue([notebook])
    out = gpu_run.directory / "out"
    out.mkdir()
    (out / name).write_text('{"text": "env: PASSWORD=s3cr3t-t0ken"}')
    (out / f"{name}.log").write_text("token s3cr3t-t0ken\n")
    (out / f"{name}.shell").write_text('[3, 128, "curl -H s3cr3t-t0ken x"]\n')

    gpu_run.fetch()

    assert "s3cr3t-t0ken" not in (out / name).read_text()
    assert (out / f"{name}.log").read_text() == "token [deckz: redacted LAB_TOKEN]\n"
    assert "s3cr3t-t0ken" not in (out / f"{name}.shell").read_text()


def test_hooked_notebooks_run_one_at_a_time_across_machines(repo: Path) -> None:
    runner = FakeRunner()
    hooks = {"reset": "reset-server"}
    light = _up(repo, runner, "light", hooks=hooks)
    heavy = _up(repo, runner, "heavy", hooks=hooks)
    fr = _notebook(repo / "demo-fr.ipynb", {"hook": "reset"}, ["1"])
    en = _notebook(repo / "demo-en.ipynb", {"hook": "reset"}, ["1"])

    def hook_runs() -> int:
        return runner.calls.count(["sh", "-c", "reset-server"])

    assert light.queue([fr]) == (["demo-fr.full.ipynb"], [])
    assert heavy.queue([en]) == ([], [en])
    assert hook_runs() == 1
    assert heavy.hooks_pending()
    assert light.finish_hooks() == []

    (light.directory / "out").mkdir()
    (light.directory / "out" / "demo-fr.full.ipynb.done").write_text("0 60\n")
    assert light.finish_hooks() == [
        "ran hook reset after demo-fr.full.ipynb",
        "queued demo-en.full.ipynb on heavy",
    ]

    # Once after the first run, not again before the second one.
    assert hook_runs() == 2
    # The held notebook's machine runs its queue again, with its last timeout.
    assert "setsid nohup bash /work/queue.sh" in runner.commands("ssh")[-1][-1]
    assert not light.hooks_pending()
    assert heavy.hooks_pending()
    assert (heavy.directory / "in" / "demo-en.full.ipynb").is_file()


def test_down_runs_the_hook_and_drops_the_notebooks_held_for_it(repo: Path) -> None:
    runner = FakeRunner()
    hooks = {"reset": "reset-server"}
    gpu_run = _up(repo, runner, "main", hooks=hooks)
    fr = _notebook(repo / "demo-fr.ipynb", {"hook": "reset"}, ["1"])
    en = _notebook(repo / "demo-en.ipynb", {"hook": "reset"}, ["1"])
    gpu_run.queue([fr, en])

    gpu_run.down()

    assert runner.calls.count(["sh", "-c", "reset-server"]) == 2
    assert not gpu_run.hooks_pending()


def test_queue_refuses_an_unknown_hook(repo: Path) -> None:
    gpu_run = _up(repo, FakeRunner(), "main")
    notebook = _notebook(repo / "demo-fr.ipynb", {"hook": "nope"}, ["1"])

    with raises(GpuRunError, match="nope"):
        gpu_run.queue([notebook])


def test_queue_again_clears_the_earlier_results(repo: Path) -> None:
    runner = FakeRunner()
    gpu_run = _up(repo, runner, "main")
    notebook = repo / "demo-fr.ipynb"
    notebook.write_text(json.dumps({"cells": [], "metadata": {}}))
    out = _executed(gpu_run.directory / "out", "demo-fr.full.ipynb")
    gpu_run.note_finished()

    gpu_run.queue([notebook])

    assert not out.exists()
    assert not out.with_name("demo-fr.full.ipynb.done").exists()
    assert json.loads((gpu_run.directory / "noted.json").read_text()) == []
    scp_at = runner.calls.index(runner.commands("scp")[-1])
    clear = runner.calls[scp_at + 1]
    assert clear[0] == "ssh"
    assert clear[-1].endswith(
        "rm -f demo-fr.full.ipynb demo-fr.full.ipynb.done"
        " demo-fr.full.ipynb.log demo-fr.full.ipynb.maxrss"
        " demo-fr.full.ipynb.shell"
    )


def _watched(repo: Path, monkeypatch: MonkeyPatch, polls: list[Any]) -> None:
    import appdirs

    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(repo))
    monkeypatch.chdir(repo)
    machine_dir = repo / ".run" / "gpu" / "main"
    machine_dir.mkdir(parents=True)
    (machine_dir / "state.json").write_text(
        json.dumps({"id": 1, "gpu": "T4", "machine": 2, "host": "h", "port": 22})
    )
    remaining = iter(polls)

    def status(_: GpuRun) -> GpuStatus:
        polled = next(remaining)
        if isinstance(polled, Exception):
            raise polled
        return polled

    monkeypatch.setattr(GpuRun, "status", status)
    monkeypatch.setattr(GpuRun, "fetch", lambda self: self.directory / "out")
    monkeypatch.setattr("time.sleep", lambda _: None)
    main(("labs", "gpu", "status", "--watch", "--plain", "--interval", "0"))


def test_cli_status_watch_keeps_polling_an_unreachable_machine(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    done = GpuStatus(
        instance=InstanceInfo(status="running"),
        queue=(QueueEntry("a.full.ipynb", "done", 0, 60),),
    )

    _watched(
        repo,
        monkeypatch,
        [GpuRunError("ssh failed"), GpuStatus(instance=None), done],
    )

    out = capsys.readouterr().out
    assert "main: unreachable (ssh failed)" in out
    assert out.count("machine\tmain\t") == 2
    assert out.rstrip().endswith("a.full.ipynb\tdone\t0\t60")


def test_cli_status_watch_gives_up_on_a_machine_unreachable_three_times(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    _watched(repo, monkeypatch, [GpuRunError("ssh failed")] * 3)

    assert "main: unreachable 3 times, given up" in capsys.readouterr().out


# -- deckz labs gpu pass -------------------------------------------------------


class PassRunner(FakeRunner):
    """A machine whose queue runs each notebook sent: rsync fetches its run."""

    def __init__(
        self,
        out: Path,
        *,
        exit_code: int = 0,
        finishes: bool = True,
        cells: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self.instances = [_running()]
        self.out = out
        self.exit_code = exit_code
        self.finishes = finishes
        self.cells = cells
        self.sent: list[str] = []

    def __call__(
        self, args: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if args[0] == "scp" and args[-1].endswith(":/work/in/"):
            self.sent += [Path(source).name for source in args[-2:-1]]
        state = "done" if self.finishes else "running"
        self.ssh_output = "".join(
            f"{name}\t{state}\t{f'{self.exit_code} 120' if self.finishes else ''}\n"
            for name in self.sent
        )
        if args[0] == "rsync" and self.finishes:
            self.out.mkdir(parents=True, exist_ok=True)
            for name in self.sent:
                cell = {
                    "cell_type": "code",
                    "source": ["print(1)"],
                    "metadata": {},
                    "execution_count": 1,
                    "outputs": [
                        {"output_type": "stream", "name": "stdout", "text": ["1\n"]}
                    ],
                }
                cells = self.cells or [cell]
                executed = {"cells": cells, "metadata": {}, "nbformat": 4}
                (self.out / name).write_text(json.dumps(executed))
                (self.out / f"{name}.done").write_text(f"{self.exit_code} 120\n")
        return super().__call__(args, **kwargs)


def _demo(repo: Path, name: str = "demo-fr.ipynb") -> Path:
    notebook = repo / "labs" / "notebooks" / "nn" / "cnn" / name
    notebook.parent.mkdir(parents=True, exist_ok=True)
    cell = {"cell_type": "code", "source": ["print(1)"], "metadata": {}, "outputs": []}
    notebook.write_text(json.dumps({"cells": [cell], "metadata": {}, "nbformat": 4}))
    return notebook


def _pass(repo: Path, runner: FakeRunner, **kwargs: Any) -> Any:
    gpu_run = _gpu_run(repo, runner)
    lines: list[str] = []
    kwargs.setdefault("max_hours", 1.0)
    result = gpu_pass.run(
        gpu_run,
        kwargs.pop("settings", None) or _settings(repo),
        kwargs.pop("notebooks", None) or [_demo(repo)],
        interval=60,
        report=lines.append,
        sleep=kwargs.pop("sleep", _no_sleep),
        **kwargs,
    )
    return gpu_run, result, lines


def _destroyed(runner: FakeRunner) -> list[list[str]]:
    return [call for call in runner.commands("vastai") if call[1] == "destroy"]


def test_pass_runs_notes_destroys_and_writes_the_outputs_back(repo: Path) -> None:
    runner = PassRunner(repo / ".run" / "gpu" / "main" / "out")
    notebook = _demo(repo)

    gpu_run, result, lines = _pass(
        repo, runner, notebooks=[notebook], write_outputs=True, clock=lambda: 0.0
    )

    assert _destroyed(runner) == [["vastai", "destroy", "instance", "100", "-y"]]
    assert gpu_run.state() is None
    assert [r.path.name for r in result.reports] == ["nn__cnn__demo-fr.full.ipynb"]
    assert (result.unfinished, result.ceiling_reached) == ([], False)
    assert "#### nn__cnn__demo-fr.full.ipynb: exit 0, 120 s" in "\n".join(lines)
    assert (
        "#### nn__cnn__demo-fr.full.ipynb"
        in (gpu_run.directory / "notes.md").read_text()
    )
    assert result.written == [notebook]
    written = json.loads(notebook.read_text())
    assert written["cells"][0]["outputs"][0]["text"] == ["1\n"]
    queue = (gpu_run.directory / "scripts" / "queue.sh.new").read_text()
    assert "timeout 3600" in queue  # The ceiling, as each run's timeout.


def test_pass_keeps_a_failed_runs_notebook_as_it_was(repo: Path) -> None:
    runner = PassRunner(repo / ".run" / "gpu" / "main" / "out", exit_code=1)
    notebook = _demo(repo)
    before = notebook.read_text()

    _, result, _ = _pass(repo, runner, notebooks=[notebook], write_outputs=True)

    assert [r.exit_code for r in result.failed] == [1]
    assert result.written == []
    assert notebook.read_text() == before
    assert len(_destroyed(runner)) == 1


def _raising(tags: list[str]) -> dict[str, Any]:
    error = {"output_type": "error", "ename": "ValueError", "evalue": "empty"}
    return {
        "cell_type": "code",
        "source": ["max([])"],
        "metadata": {"tags": tags},
        "execution_count": 1,
        "outputs": [error],
    }


def test_pass_keeps_a_notebook_whose_cell_raised_as_it_was(repo: Path) -> None:
    # The notebook carries on past a cell that raised, and exits 0.
    out = repo / ".run" / "gpu" / "main" / "out"
    runner = PassRunner(out, cells=[_raising([]), _raising(["raises-exception"])])
    notebook = _demo(repo)
    before = notebook.read_text()

    _, result, lines = _pass(repo, runner, notebooks=[notebook], write_outputs=True)

    assert [r.exit_code for r in result.failed] == [0]
    assert [e.index for e in result.failed[0].errors] == [0]  # Not the tagged one.
    assert result.written == []
    assert notebook.read_text() == before
    assert f"kept {notebook} as it was: its run failed" in lines


def test_pass_writes_every_notebook_back_when_an_outputs_hook_fails(
    repo: Path,
) -> None:
    runner = PassRunner(repo / ".run" / "gpu" / "main" / "out")
    first, second = _demo(repo), _demo(repo, "demo-en.ipynb")
    fail_on_fr = "import sys; sys.exit('no report' if 'fr' in sys.argv[-1] else 0)"
    hook = LabsOutputsHook(run=(sys.executable, "-c", fail_on_fr))
    settings = GlobalSettings(
        paths=GlobalPaths(current_dir=repo, git_dir=repo),
        labs=LabsSettings(outputs=LabsOutputsSettings(hooks={"cdn": hook})),
    )

    _, result, lines = _pass(
        repo, runner, notebooks=[first, second], write_outputs=True, settings=settings
    )

    assert sorted(result.written) == sorted([first, second])
    assert json.loads(first.read_text())["cells"][0]["outputs"][0]["text"] == ["1\n"]
    assert len(result.hook_failures) == 1
    assert "outputs hook cdn failed (1)" in result.hook_failures[0]
    assert f"ran outputs hook cdn on {second}" in lines


def test_pass_destroys_the_machine_at_its_ceiling(repo: Path) -> None:
    runner = PassRunner(repo / ".run" / "gpu" / "main" / "out", finishes=False)
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    gpu_run = _gpu_run(repo, runner)
    result = gpu_pass.run(
        gpu_run,
        _settings(repo),
        [_demo(repo)],
        max_hours=0.5,
        report=lambda _: None,
        clock=lambda: now[0],
        sleep=sleep,
    )

    assert result.ceiling_reached
    assert result.unfinished == ["nn__cnn__demo-fr.full.ipynb"]
    assert now[0] == 1800
    assert len(_destroyed(runner)) == 1


def test_pass_destroys_the_machine_on_ctrl_c_and_sigterm(repo: Path) -> None:
    for stop, expected in (
        (KeyboardInterrupt, KeyboardInterrupt),
        (None, gpu_pass.GpuPassStoppedError),
    ):
        runner = PassRunner(repo / ".run" / "gpu" / "main" / "out", finishes=False)

        def sleep(_: float, stop: Any = stop) -> None:
            if stop is None:
                os.kill(os.getpid(), signal.SIGTERM)
                time.sleep(1)  # The handler raises meanwhile.
            else:
                raise stop

        with raises(expected):
            _pass(repo, runner, sleep=sleep)

        assert len(_destroyed(runner)) == 1, expected
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL


class StoppedRunner(PassRunner):
    """A machine the pass is stopped on, with `signum`, when `when` runs."""

    def __init__(self, out: Path, signum: int, when: str) -> None:
        super().__init__(out, finishes=False)
        self.signum = signum
        self.when = when
        self.destroy_blocked: set[int] = set()

    def __call__(
        self, args: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        done = super().__call__(args, **kwargs)
        if args[:2] == ["vastai", "destroy"]:
            self.destroy_blocked = set(signal.pthread_sigmask(signal.SIG_BLOCK, []))
            # Never kill the test process: the pass's handler must still be set.
            assert signal.getsignal(self.signum) not in (signal.SIG_DFL, None)
        if args[:2] == ["vastai", self.when]:
            os.kill(os.getpid(), self.signum)
        return done


@fixture
def sighup_handled() -> Any:
    # SIGHUP may be ignored where the tests run: handled, the pass replaces it.
    previous = signal.signal(signal.SIGHUP, lambda *_: None)
    yield
    signal.signal(signal.SIGHUP, previous)


def test_pass_destroys_a_machine_stopped_while_renting(
    repo: Path, sighup_handled: None
) -> None:
    # `timeout` and a closing terminal signal the whole process group: vastai
    # too, which must still finish renting, so that the machine is destroyed.
    for signum in (signal.SIGTERM, signal.SIGHUP):
        out = repo / ".run" / "gpu" / "main" / "out"
        runner = StoppedRunner(out, signum, when="create")

        with raises(gpu_pass.GpuPassStoppedError):
            _pass(repo, runner)

        assert _destroyed(runner) == [["vastai", "destroy", "instance", "100", "-y"]]
        assert not runner.commands("ssh")  # Stopped before booting.


def test_pass_ignores_a_second_stop_signal_until_destroyed(repo: Path) -> None:
    # `timeout 60 uv run deckz ...`: the pass gets timeout's SIGTERM and the
    # one uv passes on, at once.
    runner = StoppedRunner(repo / ".run" / "gpu" / "main" / "out", signal.SIGTERM, "")

    def sleep(_: float) -> None:
        runner.when = "destroy"  # The second one, while destroying.
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(1)  # The handler raises meanwhile.

    with raises(gpu_pass.GpuPassStoppedError):
        _pass(repo, runner, sleep=sleep)

    assert len(_destroyed(runner)) == 1
    assert {signal.SIGINT, signal.SIGTERM} <= runner.destroy_blocked
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL


def test_pass_refuses_a_machine_another_pass_runs(repo: Path) -> None:
    runner = FakeRunner()
    other = _gpu_run(repo, runner)

    with gpu_pass._machine_lock(other), raises(GpuRunError, match="in use by"):
        _pass(repo, runner)

    assert runner.calls == []


def test_pass_refuses_before_renting_anything(repo: Path) -> None:
    runner = FakeRunner()
    hands_on = _demo(repo, "hands-on-fr.ipynb")
    refused = [
        ({"notebooks": [_demo(repo)], "short": True, "write_outputs": True}, "--short"),
        ({"notebooks": [hands_on], "write_outputs": True}, "hands-on"),
        ({"notebooks": [_demo(repo)], "short": True}, "SHORT_RUN"),
        ({"notebooks": [repo / "missing-fr.ipynb"]}, "no such notebook"),
    ]
    for kwargs, reason in refused:
        with raises(GpuRunError, match=reason):
            _pass(repo, runner, **kwargs)

    rented = _gpu_run(repo, runner)
    rented.directory.mkdir(parents=True, exist_ok=True)
    (rented.directory / "state.json").write_text(
        json.dumps({"id": 1, "gpu": "T4", "machine": 2})
    )
    with raises(GpuRunError, match="already rented"):
        _pass(repo, runner)
    assert runner.calls == []


def test_last_runs_keeps_each_notebooks_last_success(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "notes.md").write_text(
        "\nNoted 2026-10-01 10:00 CEST:\n#### x.full.ipynb: exit 0, 300 s, peak RAM"
        "\n\nNoted 2026-10-02 10:00 CEST:\n#### x.full.ipynb: exit 1, 20 s, peak RAM"
        "\n#### y.short.ipynb: exit 0, 40 s, peak RAM\n"
    )
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "notes.md").write_text(
        "\nNoted 2026-10-03 09:00 CEST:\n#### x.full.ipynb: exit 0, 280 s, peak RAM\n"
    )

    assert gpu_pass.last_runs([tmp_path]) == {"x.full.ipynb": 280, "y.short.ipynb": 40}


def test_cli_pass_dry_run_json_estimates_from_the_notes(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    notebook = _demo(repo)
    other = _demo(repo, "demo-en.ipynb")
    notes = repo / ".run" / "gpu" / "old" / "notes.md"
    notes.parent.mkdir(parents=True)
    notes.write_text(
        "\nNoted 2026-10-01 10:00 CEST:\n"
        "#### nn__cnn__demo-fr.full.ipynb: exit 0, 1200 s, peak RAM 1.0 GiB\n"
        "#### nn__cnn__demo-en.full.ipynb: exit 0, 600 s, peak RAM 1.0 GiB\n"
    )
    monkeypatch.setattr(
        GpuRun, "cheapest", lambda self, gpus=(): Offer(7, "Tesla T4", 42, 0.2, "FR")
    )
    monkeypatch.chdir(repo)

    main(("labs", "gpu", "pass", str(notebook), str(other), "--dry-run", "--json"))

    planned = json.loads(capsys.readouterr().out)
    assert planned["gpu"] == "Tesla T4"
    assert planned["price_per_hour"] == approx(0.2)
    assert planned["ceiling_cost"] == approx(0.8)
    assert planned["estimated_hours"] == approx(40 / 60)  # 10 min to boot, 30 to run.
    assert planned["estimated_cost"] == approx(0.2 * 40 / 60)
    # In `notebook_paths`' order.
    assert [n["last_seconds"] for n in planned["notebooks"]] == [600, 1200]
    assert planned["notebooks"][1]["notebook"] == "labs/notebooks/nn/cnn/demo-fr.ipynb"


def test_cli_pass_gpu_takes_several_values(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    fr, en = _demo(repo), _demo(repo, "demo-en.ipynb")
    asked: list[tuple[str, ...]] = []

    def cheapest(self: GpuRun, gpus: tuple[str, ...] = ()) -> None:
        asked.append(tuple(gpus))

    monkeypatch.setattr(GpuRun, "cheapest", cheapest)
    monkeypatch.chdir(fr.parent)
    for tokens in (
        ("--gpu", "RTX_A4000", "RTX_3090", "demo-fr.ipynb", str(en)),
        ("demo-fr.ipynb", str(en), "--gpu", "RTX_A4000", "RTX_3090"),
        ("--gpu", "RTX_A4000", "--gpu", "RTX_3090", "demo-fr.ipynb", str(en)),
        ("--gpu", "RTX_A4000", "RTX_3090", "--interval", "9", "demo-fr.ipynb", str(en)),
    ):
        main(("labs", "gpu", "pass", "--dry-run", "--json", *tokens))

        planned = json.loads(capsys.readouterr().out)
        assert asked.pop() == ("RTX_A4000", "RTX_3090"), tokens
        assert [Path(n["notebook"]).name for n in planned["notebooks"]] == [
            "demo-en.ipynb",
            "demo-fr.ipynb",
        ], tokens


def test_cli_status_plain_gives_the_price_and_rental_time(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    machine_dir = repo / ".run" / "gpu" / "main"
    machine_dir.mkdir(parents=True)
    (machine_dir / "state.json").write_text(
        json.dumps(
            {
                "id": 1,
                "gpu": "T4",
                "machine": 2,
                "rented_at": "2026-10-17T10:00:00+02:00",
            }
        )
    )
    monkeypatch.setattr(
        GpuRun,
        "status",
        lambda self: GpuStatus(
            instance=InstanceInfo(status="loading", gpu="Tesla T4", price=0.16),
            rented_at=self.state().rented_at,
        ),
    )
    monkeypatch.chdir(repo)

    main(("labs", "gpu", "status", "--plain"))

    assert capsys.readouterr().out == (
        "machine\tmain\tloading\tTesla T4\t0.160\t2026-10-17T10:00:00+02:00\n"
    )


def test_cli_status_offline_reads_the_state_without_the_backend(
    repo: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    for name, price in (("main", 0.16), ("old", None)):
        machine_dir = repo / ".run" / "gpu" / name
        machine_dir.mkdir(parents=True)
        state: dict[str, object] = {"id": 1, "gpu": "Tesla T4", "machine": 2}
        if price is not None:
            state |= {"price": price, "rented_at": "2026-10-17T10:00:00+02:00"}
        (machine_dir / "state.json").write_text(json.dumps(state))

    def unreachable(self: GpuRun) -> GpuStatus:
        raise AssertionError

    monkeypatch.setattr(GpuRun, "status", unreachable)
    monkeypatch.chdir(repo)

    main(("labs", "gpu", "status", "--plain", "--offline"))

    assert capsys.readouterr().out == (
        "machine\tmain\trented\tTesla T4\t0.160\t2026-10-17T10:00:00+02:00\n"
        "machine\told\trented\tTesla T4\t\t\n"
    )
