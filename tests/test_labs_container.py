import json
import subprocess
from pathlib import Path
from typing import Any

from pytest import importorskip, raises

from deckz.exceptions import LabContainerError
from deckz.labs.container import dev_container, runner_source
from deckz.labs.publishing import repository_name


def _config(tmp_path: Path, config: object) -> Path:
    path = tmp_path / ".devcontainer" / "devcontainer.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(config) if not isinstance(config, str) else config)
    return tmp_path


def test_an_image_config_needs_no_build(tmp_path: Path) -> None:
    published = _config(
        tmp_path,
        {
            "image": "example/image:1",
            "remoteUser": "root",
            "hostRequirements": {"cpus": 2, "memory": "8gb"},
        },
    )

    container = dev_container(published, "labs")

    assert container.image == "example/image:1"
    assert container.user == "root"
    assert container.workspace == "/workspaces/labs"
    assert container.limits == ("--cpus", "2", "--memory", "8g")


def test_a_config_without_image_nor_dockerfile_is_refused(tmp_path: Path) -> None:
    published = _config(tmp_path, {"name": "nothing to run"})

    with raises(LabContainerError, match="neither"):
        dev_container(published, "labs")


def test_a_config_with_comments_is_refused(tmp_path: Path) -> None:
    published = _config(tmp_path, '{\n  // a comment\n  "image": "x"\n}')

    with raises(LabContainerError, match="plain JSON"):
        dev_container(published, "labs")


def test_no_config_is_refused(tmp_path: Path) -> None:
    with raises(LabContainerError, match="no dev container"):
        dev_container(tmp_path, "labs")


def test_the_runner_compiles_and_shifts_cells_after_the_smoke_cell() -> None:
    notebook = {
        "cells": [{"cell_type": "code", "metadata": {}, "outputs": [], "source": "1"}],
        "metadata": {"flag": True, "nothing": None},
        "nbformat": 4,
    }

    plain = runner_source(notebook, ["code"], "lab-demo-fr.ipynb", smoke=False)
    smoke = runner_source(notebook, ["code"], "lab-demo-fr.ipynb", smoke=True)

    compile(plain, "<runner>", "exec")
    compile(smoke, "<runner>", "exec")
    assert "OFFSET = 0" in plain
    assert "OFFSET = 1" in smoke
    assert "__deckz_smoke()" in smoke
    assert "'lab-demo-fr.ipynb'" in plain


def test_repository_name_is_the_remote_urls_last_part(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "remote",
            "add",
            "labs",
            "git@github.com:shuuchuu/labs.git",
        ],
        check=True,
    )

    assert repository_name(tmp_path, "labs") == "labs"
    assert repository_name(tmp_path, "missing") == "missing"


def test_a_kernel_death_and_a_failure_reported_twice_read_once() -> None:
    from deckz.labs.execution import EVENT, report_lines

    events = [
        [2, "code", "ValueError: x"],
        ["kernel-died", 3, True],
        [2, "code", "ValueError: x"],
    ]
    stderr = "".join(EVENT + json.dumps(event) + "\n" for event in events)

    lines = list(report_lines(stderr, 0))

    assert lines == [
        "  [3] the kernel died: ran the notebook again from the start, as a "
        "trainee would after Colab restarts it",
        "  [2] code cell raised ValueError: x",
    ]


def test_a_prebuilt_image_with_its_dockerfile_is_built_under_its_name(
    tmp_path: Path, monkeypatch: Any
) -> None:
    published = _config(
        tmp_path,
        {
            "image": "ghcr.io/example/env:abc",
            "customizations": {"deckz": {"dockerfile": "Dockerfile"}},
        },
    )
    calls = []

    def run(command: list[Any], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(part) for part in command])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)

    container = dev_container(published, "labs")

    assert container.image == "ghcr.io/example/env:abc"
    assert calls[0][:5] == ["docker", "build", "--quiet", "--tag", container.image]
    assert calls[0][-3:-1] == [
        "--file",
        str(published / ".devcontainer" / "Dockerfile"),
    ]


def test_the_runner_runs_the_shell_guard_in_the_kernel() -> None:
    notebook = {"cells": [], "metadata": {}, "nbformat": 4}

    source = runner_source(notebook, [], "lab-demo-fr.ipynb", smoke=False)

    compile(source, "<runner>", "exec")
    assert "__deckz_shell_guard" in source
    assert "--IPKernelApp.exec_files=" in source
    assert "'/tmp/deckz-shell-failures.jsonl'" in source


def test_failed_shell_commands_are_reported_once_each_without_raising() -> None:
    from deckz.labs.execution import EVENT, report_lines

    events = [
        ["shell-failed", 1, 1, "false"],
        ["kernel-died", 3, True],
        ["shell-failed", 1, 1, "false"],
        ["shell-failed", 2, 127, "nvidia-smi"],
    ]
    stderr = "".join(EVENT + json.dumps(event) + "\n" for event in events)

    lines = list(report_lines(stderr, 0))

    assert lines == [
        "  [3] the kernel died: ran the notebook again from the start, as a "
        "trainee would after Colab restarts it",
        "  [1] shell command exited with code 1: false",
        "  [2] shell command exited with code 127: nvidia-smi",
        "  execution: no code cell raised",
    ]


def test_the_shell_guard_logs_each_failed_shell_command_in_a_real_kernel(
    tmp_path: Path,
) -> None:
    # deckz's own environment has no kernel: run with
    # `uv run --with ipykernel --with nbclient pytest`.
    importorskip("ipykernel")
    nbclient = importorskip("nbclient")
    nbformat = importorskip("nbformat")
    from deckz.labs.execution import shell_guard

    log = tmp_path / "failures.jsonl"
    guard = tmp_path / "guard.py"
    guard.write_text(shell_guard(str(log)))
    cells = [
        "!false\nran = True",
        "%pip install --quiet --no-index deckz-no-such-package",
        "!true\nassert ran and _exit_code == 0",
        "assert not [name for name in globals() if 'deckz' in name]",
    ]
    nb = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(c) for c in cells])
    client = nbclient.NotebookClient(
        nb,
        timeout=60,
        kernel_name="python3",
        resources={"metadata": {"path": str(tmp_path)}},
        extra_arguments=[f"--IPKernelApp.exec_files={guard}"],
    )

    client.execute()

    failures = [json.loads(line) for line in log.read_text().splitlines()]
    assert [code for code, _ in failures] == [1, 1]
    assert failures[0][1] == "false"
    assert "pip install --quiet --no-index deckz-no-such-package" in failures[1][1]


# -- run needs (`labs.needs`) -------------------------------------------------

_TOKEN = "pypi-AgE" + "x1" * 100
"""Longer than any truncation of the report lines: a prefix of it must not show."""


def _needs_notebook(tmp_path: Path, needs: dict[str, Any], *sources: str) -> Path:
    cells = [
        {"cell_type": "code", "metadata": {}, "outputs": [], "source": source}
        for source in sources
    ]
    path = tmp_path / "lab.ipynb"
    path.write_text(
        json.dumps({"cells": cells, "metadata": {"shuuchuu": {"run": needs}}})
    )
    return path


class _FakeDocker:
    """`docker run`, reporting the given events; records what it was sent."""

    def __init__(self, *events: list[Any], log: Path | None = None) -> None:
        self.events = events
        self.log = log
        self.sources: list[str] = []
        self.commands: list[list[str]] = []

    def __call__(self, command: list[Any], **kwargs: Any) -> Any:
        from deckz.labs.execution import EVENT

        self.commands.append([str(part) for part in command])
        if command[:2] != ["docker", "run"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        self.sources.append(kwargs["input"])
        if self.log is not None:
            with self.log.open("a") as f:
                f.write("run\n")
        stderr = "".join(EVENT + json.dumps(event) + "\n" for event in self.events)
        return subprocess.CompletedProcess(command, 0, "", stderr)


def _check(
    path: Path, docker: _FakeDocker, monkeypatch: Any, **kwargs: Any
) -> list[str]:
    from deckz.configuring.settings import LabsRunSettings
    from deckz.labs.container import Container
    from deckz.labs.execution import check_notebook

    monkeypatch.setattr(subprocess, "run", docker)
    return list(
        check_notebook(
            path,
            container=Container("image", "root", "/workspaces/labs", ()),
            run_settings=LabsRunSettings(hooks=kwargs.pop("hooks", {})),
            hooks_cwd=path.parent,
            **kwargs,
        )
    )


def test_a_set_need_is_filled_in_the_copy_sent_through_stdin_only(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("LAB_TOKEN", _TOKEN)
    path = _needs_notebook(
        tmp_path, {"secrets": {"jeton": "LAB_TOKEN"}}, 'jeton = ""\nprint(1)'
    )
    docker = _FakeDocker()

    lines = _check(path, docker, monkeypatch)

    assert repr(f"jeton = {json.dumps(_TOKEN)}\n") in docker.sources[0]
    assert all(_TOKEN not in " ".join(command) for command in docker.commands)
    assert "-e" not in docker.commands[0]
    assert "  execution: no code cell raised" in lines
    assert _TOKEN not in path.read_text()


def test_an_unset_need_runs_the_notebook_as_written_and_says_so(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from deckz.labs.execution import is_problem

    monkeypatch.delenv("LAB_TOKEN", raising=False)
    path = _needs_notebook(tmp_path, {"secrets": {"jeton": "LAB_TOKEN"}}, 'jeton = ""')
    docker = _FakeDocker()

    lines = _check(path, docker, monkeypatch)

    assert repr('jeton = ""') in docker.sources[0]
    unset = [line for line in lines if "LAB_TOKEN" in line]
    assert unset == [
        "  LAB_TOKEN not set: ran without it (set it in the environment or .env"
        " for a run with it)"
    ]
    assert not is_problem(unset[0])


def test_a_secret_is_redacted_from_a_failed_command_and_a_traceback(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("LAB_TOKEN", _TOKEN)
    path = _needs_notebook(tmp_path, {"secrets": {"jeton": "LAB_TOKEN"}}, 'jeton = ""')
    command = f"uv publish --index testpypi --token {_TOKEN}"
    docker = _FakeDocker(
        ["shell-failed", 0, 1, command],
        [0, "code", f"CalledProcessError: Command '{command}' returned 1"],
    )

    lines = _check(path, docker, monkeypatch)

    report = "\n".join(lines)
    assert "pypi-AgE" not in report
    assert (
        "  [0] shell command exited with code 1: uv publish --index testpypi"
        " --token [deckz: redacted LAB_TOKEN]"
    ) in lines
    assert "[0] code cell raised CalledProcessError: Command 'uv publish" in report


def test_the_hook_runs_before_and_after_a_failing_run(
    tmp_path: Path, monkeypatch: Any
) -> None:
    log = tmp_path / "hooks.log"
    path = _needs_notebook(tmp_path, {"hook": "reset"}, "1 / 0")
    docker = _FakeDocker([0, "code", "ZeroDivisionError: division by zero"], log=log)

    lines = _check(path, docker, monkeypatch, hooks={"reset": "echo hook >> hooks.log"})

    assert log.read_text().split() == ["hook", "run", "hook"]
    assert "  [0] code cell raised ZeroDivisionError: division by zero" in lines


def test_the_hook_runs_after_a_timed_out_run_and_reports_its_failure(
    tmp_path: Path, monkeypatch: Any
) -> None:
    log = tmp_path / "hooks.log"
    path = _needs_notebook(tmp_path, {"hook": "reset"}, "1")
    docker = _FakeDocker(log=log)

    def timed_out(command: list[Any], **kwargs: Any) -> Any:
        result = docker(command, **kwargs)
        if command[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(command, 1, stderr=b"")
        return result

    # Fails after the run only: the second time it runs.
    hook = "echo hook >> hooks.log; test $(wc -l < hooks.log) -lt 2 || exit 3"
    from deckz.configuring.settings import LabsRunSettings
    from deckz.labs.container import Container
    from deckz.labs.execution import check_notebook

    monkeypatch.setattr(subprocess, "run", timed_out)
    lines = list(
        check_notebook(
            path,
            container=Container("image", "root", "/workspaces/labs", ()),
            run_settings=LabsRunSettings(hooks={"reset": hook}),
            hooks_cwd=tmp_path,
            timeout=1,
        )
    )

    assert log.read_text().split() == ["hook", "run", "hook"]
    assert "  execution timed out after 1s, cells run until then:" in lines
    assert lines[-1].startswith("  hook reset failed (3): ")


def test_an_unknown_hook_or_a_missing_line_doesnt_run(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("LAB_TOKEN", _TOKEN)
    docker = _FakeDocker()
    unknown = _needs_notebook(tmp_path, {"hook": "nope"}, "1")

    lines = _check(unknown, docker, monkeypatch)

    assert lines[-2].startswith("  run needs: hook 'nope' is not in labs.run.hooks")
    assert lines[-1] == "  execution: not run, its run needs not met"
    missing = _needs_notebook(tmp_path, {"secrets": {"jeton": "LAB_TOKEN"}}, "1")
    lines = _check(missing, docker, monkeypatch)
    assert '  run needs: expected exactly one line `jeton = ""`' in lines
    assert docker.sources == []


def test_the_local_runner_fills_no_need_and_says_so(tmp_path: Path) -> None:
    from deckz.configuring.settings import LabsRunSettings
    from deckz.labs.execution import check_notebook, is_problem

    path = _needs_notebook(
        tmp_path,
        {"secrets": {"jeton": "LAB_TOKEN"}, "hook": "reset"},
        'jeton = ""',
    )

    lines = list(check_notebook(path, run_settings=LabsRunSettings()))

    fact = "  run needs left unfilled without --container: LAB_TOKEN, hook reset"
    assert fact in lines
    assert not is_problem(fact)
    assert "  execution: no code cell raised" in lines
