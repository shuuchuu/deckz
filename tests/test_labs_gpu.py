import json
import subprocess
from pathlib import Path
from typing import Any

from pygit2 import init_repository
from pytest import CaptureFixture, MonkeyPatch, fixture, raises

from deckz.cli import main
from deckz.configuring.settings import GlobalPaths, GlobalSettings
from deckz.exceptions import GpuRunError, MissingExtraError
from deckz.labs.gpu import GpuRun, VastBackend, format_report, report

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
            out = self.ssh_output
        return subprocess.CompletedProcess(args, 0, out, "")

    def commands(self, program: str) -> list[list[str]]:
        return [call for call in self.calls if call[0] == program]


@fixture
def repo(tmp_path: Path) -> Path:
    init_repository(str(tmp_path))
    return tmp_path


def _settings(repo: Path) -> GlobalSettings:
    return GlobalSettings(paths=GlobalPaths(current_dir=repo, git_dir=repo))


def _no_sleep(_: float) -> None:
    pass


def _gpu_run(repo: Path, runner: FakeRunner) -> GpuRun:
    settings = _settings(repo)
    return GpuRun(settings, VastBackend(settings, runner), run=runner, sleep=_no_sleep)


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
    assert json.loads((gpu_run.directory / "avoid.json").read_text()) == [42]
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

    names = gpu_run.queue([notebook], short=True)

    assert names == ["nn__cnn__demo-fr.short.ipynb"]
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

    queue = (gpu_run.directory / "scripts" / "queue.sh").read_text()
    assert "PYTHON_CPU_COUNT=2 taskset -c 0,1 timeout 600" in queue
    assert "@" not in queue


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


def test_down_destroys_and_forgets_the_machine(repo: Path) -> None:
    runner = FakeRunner()
    runner.instances = [_running()]
    gpu_run = _gpu_run(repo, runner)
    gpu_run.up()

    assert gpu_run.down() == 100
    assert gpu_run.state() is None
    assert gpu_run.down() is None


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
    _executed(repo / ".run" / "gpu" / "out")

    main(("labs", "gpu", "report", "--plain"))

    out = capsys.readouterr().out
    assert out.startswith("#### nn__demo-fr.full.ipynb: exit 0, 95 s")
    assert "[1] raised ZeroDivisionError" in out
