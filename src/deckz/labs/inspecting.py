"""Read-only views of a notebook: cell roles, stored outputs, a compact dump."""

from collections.abc import Iterator
from typing import Any

from .notebook import cell_source


def is_solution_heading(cell: dict[str, Any], *, heading: str) -> bool:
    """Whether `cell` is a markdown heading cell matching `heading`.

    Returns:
        True if it is.
    """
    if cell.get("cell_type") != "markdown":
        return False
    first = cell_source(cell).strip().splitlines()[:1]
    return bool(first) and first[0].lstrip("#").strip().lower() == heading.lower()


def roles(notebook: dict[str, Any], *, heading: str = "Solution") -> list[str]:
    """Label each cell: heading/markdown, or exercise/solution for code cells.

    Returns:
        One label per cell of `notebook`, in order.
    """
    labels: list[str] = []
    in_solution = False
    for cell in notebook["cells"]:
        if cell.get("cell_type") == "markdown":
            in_solution = is_solution_heading(cell, heading=heading)
            labels.append("solution-heading" if in_solution else "markdown")
        else:
            labels.append("solution" if in_solution else "code")
    return labels


def summarize_outputs(cell: dict[str, Any]) -> str:
    """A one-line summary of a cell's stored outputs.

    Returns:
        The summary.
    """
    parts = []
    for out in cell.get("outputs", []):
        kind = out.get("output_type")
        if kind == "error":
            parts.append(f"ERROR {out.get('ename')}: {out.get('evalue')}")
        elif kind == "stream":
            text = cell_source({"source": out.get("text", "")})
            parts.append(f"stream: {text[:200]!r}")
        else:
            parts.append(kind or "?")
    return "; ".join(parts)


def dump_lines(notebook: dict[str, Any], *, heading: str = "Solution") -> Iterator[str]:
    """A compact, readable view of a notebook's cells.

    Yields:
        One or more lines per cell: its index and role, its source, and, if \
        any, a summary of its stored outputs.
    """
    labels = roles(notebook, heading=heading)
    for i, (cell, role) in enumerate(zip(notebook["cells"], labels, strict=True)):
        yield f"--- [{i}] {role}"
        yield cell_source(cell).rstrip()
        if outputs := summarize_outputs(cell):
            yield f">>> outputs: {outputs}"
