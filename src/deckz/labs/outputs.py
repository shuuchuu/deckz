"""Write an executed notebook's outputs back into its source, cell by cell.

Running a notebook (in Jupyter, Colab, or `deckz labs run --gpu`) produces a
copy with every code cell's `outputs` and `execution_count` filled in, plus
run metadata deckz never wants to store (timestamps, widget state). This
copies only the outputs themselves, merging each cell's consecutive stream
writes into one and resolving carriage returns, so a progress bar is stored
once, as its final state, as Colab shows it.
"""

import json
from pathlib import Path
from typing import Any

from ..exceptions import LabOutputsMismatchError
from .images import recompress_output_images
from .notebook import Notebook, cell_source


def _resolve_carriage_returns(text: str) -> str:
    r"""Simulate a terminal: a `\r` discards what came before it on its line.

    Returns:
        `text`, with each line collapsed to what a terminal would display.
    """
    return "\n".join(line.rsplit("\r", 1)[-1] for line in text.split("\n"))


def _stream_text(output: dict[str, Any]) -> str:
    return cell_source({"source": output.get("text", "")})


def _merge_stream_outputs(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive stream outputs of the same name into one.

    Returns:
        `outputs`, with each run of same-named `stream` outputs merged and \
        carriage returns resolved.
    """
    merged: list[dict[str, Any]] = []
    for output in outputs:
        is_stream = output.get("output_type") == "stream"
        if (
            is_stream
            and merged
            and merged[-1].get("output_type") == "stream"
            and merged[-1].get("name") == output.get("name")
        ):
            merged[-1] = {
                **merged[-1],
                "text": _stream_text(merged[-1]) + _stream_text(output),
            }
        else:
            merged.append(dict(output))
    for output in merged:
        if output.get("output_type") == "stream":
            output["text"] = _resolve_carriage_returns(_stream_text(output)).splitlines(
                keepends=True
            )
    return merged


def apply_executed_outputs(
    notebook: Notebook,
    executed: dict[str, Any],
    *,
    recompress_images: bool = True,
    max_image_kb: int = 200,
) -> None:
    """Copy `executed`'s cell outputs into `notebook`, in place.

    Only `outputs` and `execution_count` are copied, cell by cell, no run
    metadata. Consecutive stream outputs are merged and carriage returns
    resolved (see the module docstring).

    Args:
        notebook: The notebook to update, mutated in place; call `save()` \
            afterwards to write it.
        executed: The parsed, executed copy of the same notebook.
        recompress_images: Shrink large `image/png` outputs, see \
            `deckz.labs.images.recompress_output_images`.
        max_image_kb: Passed to `recompress_output_images`.

    Raises:
        LabOutputsMismatchError: If `notebook` and `executed` don't have the \
            same number of cells.
    """
    target_cells = notebook.cells
    executed_cells = executed.get("cells", [])
    if len(target_cells) != len(executed_cells):
        msg = (
            f"{notebook.path}: {len(target_cells)} cells, the executed copy "
            f"has {len(executed_cells)}"
        )
        raise LabOutputsMismatchError(msg)
    for target_cell, executed_cell in zip(target_cells, executed_cells, strict=True):
        if target_cell.get("cell_type") != "code":
            continue
        target_cell["execution_count"] = executed_cell.get("execution_count")
        outputs = _merge_stream_outputs(executed_cell.get("outputs", []))
        if recompress_images:
            recompress_output_images(outputs, max_image_kb=max_image_kb)
        target_cell["outputs"] = outputs


def write_outputs(
    executed_path: Path,
    notebook_path: Path,
    *,
    solution_heading: str = "Solution",
    recompress_images: bool = True,
    max_image_kb: int = 200,
) -> None:
    """Load `notebook_path`, apply `executed_path`'s outputs, and save it.

    Args:
        executed_path: Path to the executed copy, read for its cells' outputs.
        notebook_path: Path to the notebook to update and save.
        solution_heading: Passed to `Notebook`, to keep its collapsed \
            sections in sync on save.
        recompress_images: Passed to `apply_executed_outputs`.
        max_image_kb: Passed to `apply_executed_outputs`.
    """
    notebook = Notebook(notebook_path, solution_heading=solution_heading)
    executed = json.loads(executed_path.read_text(encoding="utf-8"))
    apply_executed_outputs(
        notebook,
        executed,
        recompress_images=recompress_images,
        max_image_kb=max_image_kb,
    )
    notebook.save()
