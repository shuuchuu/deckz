import base64
import json
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter
from pytest import raises

from deckz.exceptions import LabOutputsMismatchError
from deckz.labs.notebook import Notebook, canonical_dump
from deckz.labs.outputs import apply_executed_outputs, write_outputs


def _notebook(cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


def _code_cell(**kwargs: Any) -> dict[str, Any]:
    return {
        "cell_type": "code",
        "metadata": {},
        "source": ["print(1)"],
        "execution_count": None,
        "outputs": [],
        **kwargs,
    }


def test_apply_executed_outputs_copies_execution_count_and_outputs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    executed = _notebook(
        [
            _code_cell(
                execution_count=1,
                outputs=[{"output_type": "execute_result", "data": {}}],
            )
        ]
    )

    apply_executed_outputs(notebook, executed)

    assert notebook.cells[0]["execution_count"] == 1
    assert notebook.cells[0]["outputs"] == [
        {"output_type": "execute_result", "data": {}}
    ]


def test_apply_executed_outputs_ignores_non_code_cells(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    markdown_cell = {"cell_type": "markdown", "metadata": {}, "source": ["# Title"]}
    path.write_text(canonical_dump(_notebook([markdown_cell])))
    notebook = Notebook(path)
    executed = _notebook([dict(markdown_cell)])

    apply_executed_outputs(notebook, executed)

    assert "outputs" not in notebook.cells[0]


def test_apply_executed_outputs_raises_on_cell_count_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell(), _code_cell()])))
    notebook = Notebook(path)
    executed = _notebook([_code_cell()])

    with raises(LabOutputsMismatchError):
        apply_executed_outputs(notebook, executed)


def test_apply_executed_outputs_merges_consecutive_stream_outputs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    executed = _notebook(
        [
            _code_cell(
                outputs=[
                    {"output_type": "stream", "name": "stdout", "text": ["a"]},
                    {"output_type": "stream", "name": "stdout", "text": ["b\n"]},
                ]
            )
        ]
    )

    apply_executed_outputs(notebook, executed)

    outputs = notebook.cells[0]["outputs"]
    assert len(outputs) == 1
    assert outputs[0]["text"] == ["ab\n"]


def test_apply_executed_outputs_keeps_different_stream_names_separate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    executed = _notebook(
        [
            _code_cell(
                outputs=[
                    {"output_type": "stream", "name": "stdout", "text": "out"},
                    {"output_type": "stream", "name": "stderr", "text": "err"},
                ]
            )
        ]
    )

    apply_executed_outputs(notebook, executed)

    assert len(notebook.cells[0]["outputs"]) == 2


def test_apply_executed_outputs_resolves_carriage_returns(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    executed = _notebook(
        [
            _code_cell(
                outputs=[
                    {
                        "output_type": "stream",
                        "name": "stdout",
                        "text": "10%\r50%\r100%\ndone\n",
                    }
                ]
            )
        ]
    )

    apply_executed_outputs(notebook, executed)

    assert notebook.cells[0]["outputs"][0]["text"] == ["100%\n", "done\n"]


def _photo_like_png_b64() -> str:
    channels = [
        Image.effect_noise((300, 300), 40).filter(ImageFilter.GaussianBlur(6))
        for _ in range(3)
    ]
    buffer = BytesIO()
    Image.merge("RGB", channels).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_apply_executed_outputs_recompresses_large_images_by_default(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    executed = _notebook(
        [
            _code_cell(
                outputs=[
                    {
                        "output_type": "display_data",
                        "data": {"image/png": _photo_like_png_b64()},
                    }
                ]
            )
        ]
    )

    apply_executed_outputs(notebook, executed, max_image_kb=1)

    data = notebook.cells[0]["outputs"][0]["data"]
    assert "image/png" not in data
    assert "image/jpeg" in data


def test_apply_executed_outputs_skips_recompression_when_disabled(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(canonical_dump(_notebook([_code_cell()])))
    notebook = Notebook(path)
    png_b64 = _photo_like_png_b64()
    executed = _notebook(
        [
            _code_cell(
                outputs=[
                    {"output_type": "display_data", "data": {"image/png": png_b64}}
                ]
            )
        ]
    )

    apply_executed_outputs(notebook, executed, recompress_images=False, max_image_kb=1)

    data = notebook.cells[0]["outputs"][0]["data"]
    assert data == {"image/png": png_b64}


def test_write_outputs_saves_notebook_in_canonical_style(tmp_path: Path) -> None:
    notebook_path = tmp_path / "demo.ipynb"
    notebook_path.write_text(
        json.dumps(_notebook([_code_cell()]), separators=(",", ":"))
    )
    executed_path = tmp_path / "executed.ipynb"
    executed_path.write_text(json.dumps(_notebook([_code_cell(execution_count=2)])))

    write_outputs(executed_path, notebook_path)

    written = json.loads(notebook_path.read_text())
    assert written["cells"][0]["execution_count"] == 2
    assert notebook_path.read_text() == canonical_dump(written)
