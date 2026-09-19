import json
from pathlib import Path
from typing import Any

from deckz.extras.labs import normalize_notebook, notebook_paths


def _write_notebook(path: Path, cells: list[dict[str, Any]], **metadata: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    notebook = {
        "cells": cells,
        "metadata": metadata,
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(notebook, indent=1, sort_keys=True) + "\n")


def _read_notebook(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _markdown_cell(heading: str, **metadata: Any) -> dict[str, Any]:
    return {
        "cell_type": "markdown",
        "metadata": metadata,
        "source": [f"# {heading}\n", "some text"],
    }


def _code_cell() -> dict[str, Any]:
    return {"cell_type": "code", "metadata": {}, "source": ["x = 1"]}


def test_normalize_notebook_collapses_solution_and_disables_ai(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    _write_notebook(
        path, [_markdown_cell("Exercise"), _code_cell(), _markdown_cell("Solution")]
    )

    changed = normalize_notebook(path)

    assert changed
    notebook = _read_notebook(path)
    colab = notebook["metadata"]["colab"]
    assert colab["generative_ai_disabled"] is True
    solution_id = notebook["cells"][2]["metadata"]["id"]
    assert colab["collapsed_sections"] == [solution_id]


def test_normalize_notebook_is_case_insensitive(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    _write_notebook(path, [_markdown_cell("solution")])

    normalize_notebook(path)

    notebook = _read_notebook(path)
    assert len(notebook["metadata"]["colab"]["collapsed_sections"]) == 1


def test_normalize_notebook_reuses_existing_cell_id(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    _write_notebook(path, [_markdown_cell("Solution", id="existing-id")])

    normalize_notebook(path)

    notebook = _read_notebook(path)
    assert notebook["cells"][0]["metadata"]["id"] == "existing-id"
    assert notebook["metadata"]["colab"]["collapsed_sections"] == ["existing-id"]


def test_normalize_notebook_drops_stale_collapsed_id(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    _write_notebook(
        path,
        [_markdown_cell("Solution", id="current-id")],
        colab={"collapsed_sections": ["stale-id", "current-id"]},
    )

    normalize_notebook(path)

    notebook = _read_notebook(path)
    assert notebook["metadata"]["colab"]["collapsed_sections"] == ["current-id"]


def test_normalize_notebook_not_changed_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    _write_notebook(path, [_markdown_cell("Solution")])
    normalize_notebook(path)

    changed_again = normalize_notebook(path)

    assert not changed_again


def test_normalize_notebook_dry_run_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    _write_notebook(path, [_markdown_cell("Solution")])
    before = path.read_text()

    changed = normalize_notebook(path, dry_run=True)

    assert changed
    assert path.read_text() == before


def test_normalize_notebook_without_solution_still_disables_ai(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    _write_notebook(path, [_markdown_cell("Exercise"), _code_cell()])

    changed = normalize_notebook(path)

    assert changed
    notebook = _read_notebook(path)
    assert notebook["metadata"]["colab"]["generative_ai_disabled"] is True
    assert notebook["metadata"]["colab"]["collapsed_sections"] == []


def test_notebook_paths_expands_directories_recursively(tmp_path: Path) -> None:
    top = tmp_path / "top.ipynb"
    nested = tmp_path / "nested" / "deep.ipynb"
    other = tmp_path / "notes.txt"
    top.write_text("{}")
    nested.parent.mkdir()
    nested.write_text("{}")
    other.write_text("not a notebook")

    result = list(notebook_paths([tmp_path]))

    assert result == sorted([top, nested])


def test_notebook_paths_deduplicates_overlapping_inputs(tmp_path: Path) -> None:
    notebook = tmp_path / "demo.ipynb"
    notebook.write_text("{}")

    result = list(notebook_paths([notebook, tmp_path]))

    assert result == [notebook]
