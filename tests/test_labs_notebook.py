import json
from pathlib import Path
from typing import Any

from deckz.labs.notebook import (
    Notebook,
    canonical_dump,
    fmt_notebook,
    notebook_paths,
    pair,
    sync_collapsed_sections,
)


def _notebook(cells: list[dict[str, Any]], **metadata: Any) -> dict[str, Any]:
    return {"cells": cells, "metadata": metadata, "nbformat": 4, "nbformat_minor": 5}


def _markdown_cell(heading: str, **metadata: Any) -> dict[str, Any]:
    return {
        "cell_type": "markdown",
        "metadata": metadata,
        "source": [f"# {heading}\n", "some text"],
    }


def _code_cell(**kwargs: Any) -> dict[str, Any]:
    return {"cell_type": "code", "metadata": {}, "source": ["x = 1"], **kwargs}


def test_sync_collapsed_sections_collapses_matching_heading() -> None:
    notebook = _notebook([_markdown_cell("Exercise"), _markdown_cell("Solution")])

    changed = sync_collapsed_sections(notebook, heading="Solution")

    assert changed
    solution_id = notebook["cells"][1]["metadata"]["id"]
    assert notebook["metadata"]["colab"]["collapsed_sections"] == [solution_id]


def test_sync_collapsed_sections_is_case_insensitive() -> None:
    notebook = _notebook([_markdown_cell("solution")])

    sync_collapsed_sections(notebook, heading="Solution")

    assert len(notebook["metadata"]["colab"]["collapsed_sections"]) == 1


def test_sync_collapsed_sections_drops_stale_id() -> None:
    notebook = _notebook(
        [_markdown_cell("Solution", id="current")],
        colab={"collapsed_sections": ["stale", "current"]},
    )

    sync_collapsed_sections(notebook, heading="Solution")

    assert notebook["metadata"]["colab"]["collapsed_sections"] == ["current"]


def test_sync_collapsed_sections_not_changed_is_idempotent() -> None:
    notebook = _notebook([_markdown_cell("Solution")])
    sync_collapsed_sections(notebook, heading="Solution")

    assert not sync_collapsed_sections(notebook, heading="Solution")


def test_canonical_dump_sorts_keys_and_lists_source_lines() -> None:
    notebook = _notebook([_code_cell(source="line1\nline2")])

    dumped = canonical_dump(notebook)

    assert json.loads(dumped)["cells"][0]["source"] == ["line1\n", "line2"]
    assert dumped.endswith("\n")
    # Sorted keys: "cell_type" before "metadata" before "source".
    assert dumped.index('"cell_type"') < dumped.index('"metadata"')


def test_fmt_notebook_rewrites_compact_notebook(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(json.dumps(_notebook([_code_cell()]), separators=(",", ":")))

    changed = fmt_notebook(path, heading="Solution")

    assert changed
    assert path.read_text() == canonical_dump(json.loads(path.read_text()))


def test_fmt_notebook_dry_run_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    before = json.dumps(_notebook([_code_cell()]), separators=(",", ":"))
    path.write_text(before)

    changed = fmt_notebook(path, heading="Solution", dry_run=True)

    assert changed
    assert path.read_text() == before


def test_fmt_notebook_already_canonical_is_noop(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))

    assert not fmt_notebook(path, heading="Solution")


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


def test_notebook_replace_matches_exact_count(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell(source=["x = 1"])])))
    notebook = Notebook(path)

    notebook.replace(0, "1", "2")

    assert notebook.source(0) == "x = 2"


def test_notebook_replace_raises_on_count_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell(source=["x = 1"])])))
    notebook = Notebook(path)

    try:
        notebook.replace(0, "missing", "2")
    except AssertionError:
        pass
    else:
        msg = "expected an AssertionError"
        raise AssertionError(msg)


def test_notebook_one_finds_single_match(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(
        canonical_dump(_notebook([_code_cell(source=["a"]), _code_cell(source=["b"])]))
    )
    notebook = Notebook(path)

    assert notebook.one("b") == 1


def test_notebook_insert_and_delete(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell(source=["a"])])))
    notebook = Notebook(path)

    notebook.insert(0, [("markdown", "# Title")])
    assert len(notebook.cells) == 2
    assert notebook.cells[0]["cell_type"] == "markdown"

    notebook.delete(0)
    assert len(notebook.cells) == 1


def test_notebook_clear_outputs(tmp_path: Path) -> None:
    cell = _code_cell(execution_count=3, outputs=[{"output_type": "stream"}])
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([cell])))
    notebook = Notebook(path)

    notebook.clear_outputs(0)

    assert notebook.cells[0]["outputs"] == []
    assert notebook.cells[0]["execution_count"] is None


def test_notebook_save_writes_canonical_style_and_syncs_collapsed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(
        json.dumps(_notebook([_markdown_cell("Solution")]), separators=(",", ":"))
    )
    notebook = Notebook(path, solution_heading="Solution")

    notebook.save()

    on_disk = json.loads(path.read_text())
    assert on_disk["metadata"]["colab"]["collapsed_sections"]
    assert path.read_text() == canonical_dump(notebook.nb)


def test_pair_returns_fr_and_en_notebooks(tmp_path: Path) -> None:
    (tmp_path / "lab-fr.ipynb").write_text(canonical_dump(_notebook([])))
    (tmp_path / "lab-en.ipynb").write_text(canonical_dump(_notebook([])))

    fr, en = pair(tmp_path, "lab")

    assert fr.path == tmp_path / "lab-fr.ipynb"
    assert en.path == tmp_path / "lab-en.ipynb"
