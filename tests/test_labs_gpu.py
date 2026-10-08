import json
import subprocess
from pathlib import Path
from typing import Any

from pygit2 import init_repository
from pytest import CaptureFixture, MonkeyPatch, fixture, raises

from deckz.cli import main
from deckz.configuring.settings import (
    GlobalPaths,
    GlobalSettings,
    LabsGpuSettings,
    LabsSettings,
)
from deckz.exceptions import GpuRunError, MissingExtraError
from deckz.labs.gpu import GpuRun, VastBackend, format_report, machines, report

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
    assert "PYTHON_CPU_COUNT=2 taskset -c 0,1 timeout 600" in queue
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

    gpu_run.fetch()

    assert "s3cr3t-t0ken" not in (out / name).read_text()
    assert (out / f"{name}.log").read_text() == "token [deckz: redacted LAB_TOKEN]\n"


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
    )
