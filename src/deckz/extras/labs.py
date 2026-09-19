"""Normalize Jupyter notebooks to this project's Colab conventions.

Two things get kept in sync on every normalized notebook:

- `metadata.colab.collapsed_sections`: every markdown heading cell whose \
    text is exactly "Solution" (case-insensitive) is collapsed by default \
    when the notebook is opened in Colab.
- `metadata.colab.generative_ai_disabled`: always set to `True`, so \
    Colab's generative AI features are off in every distributed notebook.
"""

import json
import secrets
import string
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

_ID_ALPHABET = string.ascii_letters + string.digits + "-_"


def _make_cell_id() -> str:
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(12))


def _heading_text(cell: dict[str, Any]) -> str | None:
    if cell.get("cell_type") != "markdown":
        return None
    source = "".join(cell.get("source", []))
    stripped = source.strip()
    if not stripped:
        return None
    first_line = stripped.splitlines()[0]
    if not first_line.lstrip().startswith("#"):
        return None
    return first_line.lstrip("#").strip()


def notebook_paths(paths: Iterable[Path]) -> Iterator[Path]:
    """Expand a mix of notebook files and directories into notebook files.

    Args:
        paths: Files or directories to expand. Directories are searched \
            recursively for `*.ipynb` files.

    Yields:
        Every distinct notebook path, in a stable, sorted order.
    """
    found: set[Path] = set()
    for path in paths:
        if path.is_dir():
            found.update(path.rglob("*.ipynb"))
        else:
            found.add(path)
    yield from sorted(found)


def normalize_notebook(path: Path, *, dry_run: bool = False) -> bool:
    """Normalize one notebook's Colab metadata in place.

    Args:
        path: Path to the `.ipynb` file to normalize.
        dry_run: Report whether the notebook would change, without writing \
            it.

    Returns:
        True if the notebook was (or, with `dry_run`, would be) changed.
    """
    raw = path.read_text(encoding="utf-8")
    indented = raw.startswith("{\n")
    notebook = json.loads(raw)

    solution_ids = []
    for cell in notebook["cells"]:
        if (_heading_text(cell) or "").lower() != "solution":
            continue
        metadata = cell.setdefault("metadata", {})
        cell_id = metadata.get("id")
        if not cell_id:
            cell_id = _make_cell_id()
            metadata["id"] = cell_id
        solution_ids.append(cell_id)

    all_cell_ids = {cell.get("metadata", {}).get("id") for cell in notebook["cells"]}
    colab_metadata = notebook.setdefault("metadata", {}).setdefault("colab", {})
    existing_collapsed = colab_metadata.get("collapsed_sections", [])
    kept = [cell_id for cell_id in existing_collapsed if cell_id in all_cell_ids]
    collapsed_sections = kept + [
        cell_id for cell_id in solution_ids if cell_id not in kept
    ]

    changed = collapsed_sections != existing_collapsed or not colab_metadata.get(
        "generative_ai_disabled"
    )
    if not changed:
        return False

    colab_metadata["collapsed_sections"] = collapsed_sections
    colab_metadata["generative_ai_disabled"] = True

    if not dry_run:
        dump = (
            json.dumps(notebook, indent=1, sort_keys=True, ensure_ascii=False)
            if indented
            else json.dumps(notebook, separators=(",", ":"), ensure_ascii=False)
        )
        if raw.endswith("\n"):
            dump += "\n"
        path.write_text(dump, encoding="utf-8")
    return True
