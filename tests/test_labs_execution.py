import json
import sys
from pathlib import Path
from typing import Any

from pytest import mark

from deckz.labs.execution import DATASET_FETCH, check_notebook, runner_source

_GHSPARSE = "https://github.com/shuuchuu/datasets/raw/refs/heads/main/ghsparse.sh"
_FETCH = f"wget -q {_GHSPARSE} -O /tmp/ghsparse.sh && bash /tmp/ghsparse.sh landscape"
_PIPED_FETCH = f"wget -qO- {_GHSPARSE} | bash -s landscape"


def _write_notebook(path: Path, cells: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"cells": cells, "metadata": {}}))


def _code(source: str) -> dict[str, Any]:
    return {"cell_type": "code", "metadata": {}, "source": source, "outputs": []}


@mark.parametrize("line", [_FETCH, _PIPED_FETCH])
def test_the_dataset_fetch_is_recognized_in_both_forms(line: str) -> None:
    assert DATASET_FETCH.fullmatch(line)


@mark.parametrize(
    "line",
    [
        f"{_FETCH}; rm -rf ~",
        _FETCH.replace("bash /tmp/ghsparse.sh", "bash /tmp/other.sh"),
        _FETCH.replace("-O /tmp/ghsparse.sh", "-O /tmp/other.sh"),
        _FETCH.replace("shuuchuu/datasets", "someone/datasets"),
        f"{_PIPED_FETCH} && git push",
    ],
)
def test_the_dataset_fetch_is_recognized_exactly(line: str) -> None:
    assert not DATASET_FETCH.fullmatch(line)


def test_the_local_runner_fetches_into_its_own_directory() -> None:
    # Not /tmp, which parallel checks would share.
    namespace: dict[str, Any] = {"__name__": "runner"}
    exec(compile(runner_source(), "<runner>", "exec"), namespace)
    calls: list[dict[str, Any]] = []

    class FakeSubprocess:
        @staticmethod
        def run(**kwargs: Any) -> Any:
            calls.append(kwargs)
            return type("Done", (), {"returncode": 0})()

    namespace["shell"](f"{_FETCH}\n", _subprocess=FakeSubprocess)

    assert calls[0]["shell"] is True
    assert calls[0]["args"].strip() == (
        f"wget -q {_GHSPARSE} -O ghsparse.sh && bash ghsparse.sh landscape"
    )


def test_check_notebook_reports_a_raising_cell(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    _write_notebook(path, [_code("raise ValueError('boom')")])

    lines = list(check_notebook(path, python=sys.executable, timeout=30))

    assert any("ValueError" in line for line in lines)


def test_check_notebook_reports_success(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    _write_notebook(path, [_code("x = 1")])

    lines = list(check_notebook(path, python=sys.executable, timeout=30))

    assert any("no code cell raised" in line for line in lines)


def test_check_notebook_reports_a_failed_shell_command_and_runs_on(
    tmp_path: Path,
) -> None:
    # As in IPython: the failure doesn't raise, the cell goes on.
    path = tmp_path / "demo.ipynb"
    _write_notebook(
        path,
        [
            _code("%%writefile fail.py\nimport sys\nsys.exit(3)"),
            _code("!python fail.py\nafter = True"),
            _code("assert after"),
        ],
    )

    lines = list(check_notebook(path, python=sys.executable, timeout=30))

    assert "  [1] shell command exited with code 3: python fail.py" in lines
    assert "  execution: no code cell raised" in lines


def test_smoke_caps_a_lightning_installed_after_it(tmp_path: Path) -> None:
    # A lab's `!pip install lightning` runs after the smoke code: it caps the
    # Trainer when the notebook first imports it.
    trainer = (
        "class Trainer:\n  def __init__(self, **kwargs):\n    self.kwargs = kwargs\n"
    )
    path = tmp_path / "demo.ipynb"
    _write_notebook(
        path,
        [
            _code(
                "import pathlib, sys\n"
                f"pathlib.Path('lightning.py').write_text({trainer!r})\n"
                "sys.path.insert(0, '.')"
            ),
            _code(
                "import lightning\n"
                "kwargs = lightning.Trainer(max_epochs=50, max_steps=9).kwargs\n"
                "assert kwargs['max_epochs'] == 1, kwargs\n"
                "assert 'max_steps' not in kwargs, kwargs"
            ),
        ],
    )

    lines = list(check_notebook(path, python=sys.executable, smoke=True, timeout=30))

    assert "  execution: no code cell raised" in lines


def test_check_notebook_flags_missing_solution_section(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    _write_notebook(path, [_code("x = 1")])

    lines = list(check_notebook(path, python=sys.executable, timeout=30))

    assert any("no Solution section at all" in line for line in lines)


def test_check_notebook_flags_uncollapsed_solution_heading(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    _write_notebook(
        path,
        [
            {
                "cell_type": "markdown",
                "metadata": {"id": "abc"},
                "source": ["# Solution"],
            },
            _code("x = 1"),
        ],
    )

    lines = list(check_notebook(path, python=sys.executable, timeout=30))

    assert any("not collapsed" in line for line in lines)


def test_check_notebook_uses_the_configured_heading(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    _write_notebook(
        path,
        [
            {
                "cell_type": "markdown",
                "metadata": {"id": "abc"},
                "source": ["# Correction"],
            },
            _code("x = 1"),
        ],
    )

    lines = list(
        check_notebook(path, heading="Correction", python=sys.executable, timeout=30)
    )

    assert any("Correction heading not collapsed" in line for line in lines)
