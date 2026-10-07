import json
import sys
from pathlib import Path
from typing import Any

from deckz.labs.execution import check_notebook


def _write_notebook(path: Path, cells: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"cells": cells, "metadata": {}}))


def _code(source: str) -> dict[str, Any]:
    return {"cell_type": "code", "metadata": {}, "source": source, "outputs": []}


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
