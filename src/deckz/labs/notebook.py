"""Edit lab notebooks from a script without churning their JSON formatting.

Every notebook deckz writes (`Notebook.save()`, `deckz labs fmt`) uses one
canonical JSON style: indent 1, sorted keys, every cell's `source` as a list
of lines (nbformat's own convention), so a notebook's JSON is readable as is
and a one-cell edit stays a one-cell diff.

Use `Notebook` from a throwaway script, with `PYTHONPATH` set so `deckz` is
importable (or `uv run python` in deckz's own virtualenv):

    from deckz.labs import pair

    fr, en = pair(notebooks_dir, "nn/rnn/text-generation-lightning/hands-on")
    i = fr.one("def generate(")  # the only cell containing this text
    fr.replace(i, "temperature=1.0", "temperature=0.8")
    fr.insert(i + 1, [("markdown", "### Solution"), ("code", "print(1)")])
    fr.save()

Every lookup and replacement asserts it matched exactly as expected, so a
stale anchor fails loudly instead of editing the wrong cell. A cell's source
has no trailing newline: anchor on text inside it, not on its end.
"""

import json
import secrets
import string
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

_ID_ALPHABET = string.ascii_letters + string.digits + "-_"


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


def _make_cell_id() -> str:
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(12))


def cell_source(cell: dict[str, Any]) -> str:
    """A cell's `source`, whether stored as a string or a list of lines.

    Returns:
        The source, joined into one string.
    """
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else source


def _heading_text(cell: dict[str, Any]) -> str | None:
    if cell.get("cell_type") != "markdown":
        return None
    stripped = cell_source(cell).strip()
    if not stripped:
        return None
    first_line = stripped.splitlines()[0]
    if not first_line.lstrip().startswith("#"):
        return None
    return first_line.lstrip("#").strip()


def sync_collapsed_sections(
    notebook: dict[str, Any], *, heading: str, force: bool = False
) -> bool:
    """Keep Colab's `collapsed_sections` matching the notebook's `heading` cells.

    Every markdown heading cell whose text is exactly `heading`
    (case-insensitive) is collapsed by default when the notebook is opened in
    Colab; a stale id (of a cell that no longer exists) is dropped.

    Args:
        notebook: The notebook, mutated in place.
        heading: The heading text marking a cell to collapse.
        force: Write `collapsed_sections` (even to `[]`) and create the \
            `metadata.colab` dict even if nothing would otherwise change \
            -- for a caller that's writing the notebook back regardless, \
            e.g. because something else about it changed too.

    Returns:
        True if `notebook`'s `collapsed_sections` changed.
    """
    heading_lower = heading.lower()
    solution_ids = []
    for cell in notebook.get("cells", []):
        if (_heading_text(cell) or "").lower() != heading_lower:
            continue
        metadata = cell.setdefault("metadata", {})
        cell_id = metadata.get("id")
        if not cell_id:
            cell_id = _make_cell_id()
            metadata["id"] = cell_id
        solution_ids.append(cell_id)

    all_cell_ids = {cell.get("metadata", {}).get("id") for cell in notebook["cells"]}
    existing_colab = notebook.get("metadata", {}).get("colab", {})
    existing = existing_colab.get("collapsed_sections", [])
    kept = [cell_id for cell_id in existing if cell_id in all_cell_ids]
    collapsed = kept + [cell_id for cell_id in solution_ids if cell_id not in kept]
    changed = collapsed != existing
    if not (changed or force):
        return False
    notebook.setdefault("metadata", {}).setdefault("colab", {})[
        "collapsed_sections"
    ] = collapsed
    return changed


def canonical_dump(notebook: dict[str, Any]) -> str:
    """Serialize `notebook` in deckz's canonical style (see the module docstring).

    Returns:
        The JSON text, ending with a newline.
    """
    cells = [
        {**cell, "source": cell_source(cell).splitlines(keepends=True)}
        for cell in notebook.get("cells", [])
    ]
    return (
        json.dumps(
            {**notebook, "cells": cells},
            indent=1,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )


def fmt_notebook(
    path: Path, *, heading: str = "Solution", dry_run: bool = False
) -> bool:
    """Rewrite one notebook in deckz's canonical style, if it isn't already.

    Args:
        path: Path to the `.ipynb` file.
        heading: Passed to `sync_collapsed_sections`, to also canonicalize \
            `collapsed_sections` while at it.
        dry_run: Report whether the notebook would change, without writing \
            it.

    Returns:
        True if the notebook was (or, with `dry_run`, would be) changed.
    """
    before = path.read_text(encoding="utf-8")
    notebook = json.loads(before)
    sync_collapsed_sections(notebook, heading=heading)
    after = canonical_dump(notebook)
    if after == before:
        return False
    if not dry_run:
        path.write_text(after, encoding="utf-8")
    return True


class Notebook:
    """One notebook, read from `path` and written back by `save()`.

    Every lookup and replacement asserts it matched exactly as expected, so a
    stale anchor fails loudly instead of editing the wrong cell. A cell's
    source has no trailing newline: anchor on text inside it, not on its end.
    """

    def __init__(self, path: Path, *, solution_heading: str = "Solution") -> None:
        self.path = path
        self._solution_heading = solution_heading
        self.nb: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    @property
    def cells(self) -> list[dict[str, Any]]:
        return self.nb["cells"]

    def source(self, i: int) -> str:
        return cell_source(self.cells[i])

    def set_source(self, i: int, text: str) -> None:
        self.cells[i]["source"] = text.splitlines(keepends=True)

    def replace(self, i: int, old: str, new: str, count: int = 1) -> None:
        """Replace `old`, which cell `i` must contain exactly `count` times.

        Raises:
            AssertionError: If cell `i` doesn't contain `old` exactly `count` times.
        """
        source = self.source(i)
        found = source.count(old)
        if found != count:
            msg = (
                f"{self.path.name}: cell {i} contains {old!r} {found} time(s), "
                f"not {count}"
            )
            raise AssertionError(msg)
        self.set_source(i, source.replace(old, new))

    def find(self, needle: str) -> list[int]:
        """Return the indices of the cells containing `needle`."""
        return [i for i in range(len(self.cells)) if needle in self.source(i)]

    def one(self, needle: str) -> int:
        """Return the index of the only cell containing `needle`.

        Raises:
            AssertionError: If `needle` isn't in exactly one cell.
        """
        found = self.find(needle)
        if len(found) != 1:
            msg = f"{self.path.name}: {needle!r} found in cells {found}, not exactly 1"
            raise AssertionError(msg)
        return found[0]

    def _new_cell(self, kind: str, text: str) -> dict[str, Any]:
        cell: dict[str, Any] = {
            "cell_type": kind,
            "metadata": {},
            "source": text.splitlines(keepends=True),
        }
        if any("id" in c for c in self.cells):
            cell["id"] = uuid.uuid4().hex[:12]
        # Colab's own cell ids, which `collapsed_sections` refers to.
        if any("id" in c.get("metadata", {}) for c in self.cells):
            cell["metadata"]["id"] = _make_cell_id()
        if kind == "code":
            cell["execution_count"] = None
            cell["outputs"] = []
        return cell

    def insert(self, i: int, cells: list[tuple[str, str]]) -> None:
        """Insert `(kind, text)` cells before cell `i` (kind: markdown or code)."""
        self.cells[i:i] = [self._new_cell(kind, text) for kind, text in cells]

    def delete(self, i: int) -> None:
        del self.cells[i]

    def clear_outputs(self, i: int) -> None:
        cell = self.cells[i]
        if cell["cell_type"] == "code":
            cell["outputs"] = []
            cell["execution_count"] = None

    def headings(self) -> list[str]:
        """Return the notebook's markdown heading lines, to compare fr and en."""
        return [
            line
            for i, cell in enumerate(self.cells)
            if cell["cell_type"] == "markdown"
            for line in self.source(i).splitlines()
            if line.startswith("#")
        ]

    def save(self) -> None:
        """Write the notebook back, in deckz's canonical style.

        Re-syncs the collapsed "Solution" sections first (see
        `sync_collapsed_sections`).
        """
        sync_collapsed_sections(self.nb, heading=self._solution_heading)
        self.path.write_text(canonical_dump(self.nb), encoding="utf-8")


def pair(
    notebooks_dir: Path, prefix: str, *, solution_heading: str = "Solution"
) -> tuple[Notebook, Notebook]:
    """A lab's fr and en notebooks, e.g. `pair(dir, "nlp/tf-idf-lsa/hands-on")`.

    Returns:
        The two notebooks.
    """
    return (
        Notebook(
            notebooks_dir / f"{prefix}-fr.ipynb", solution_heading=solution_heading
        ),
        Notebook(
            notebooks_dir / f"{prefix}-en.ipynb", solution_heading=solution_heading
        ),
    )
