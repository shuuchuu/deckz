"""Normalize Jupyter notebooks to their Colab conventions.

Two things get kept in sync on every normalized notebook:

- `metadata.colab.collapsed_sections`: every markdown heading cell whose \
    text matches the configured solution heading is collapsed by default \
    when the notebook is opened in Colab.
- `metadata.colab.generative_ai_disabled`: always set to `True`, so Colab's \
    generative AI features are off in every distributed notebook.
"""

import json
from pathlib import Path

from .notebook import sync_collapsed_sections


def normalize_notebook(
    path: Path, *, solution_heading: str = "Solution", dry_run: bool = False
) -> bool:
    """Normalize one notebook's Colab metadata in place.

    Keeps whichever JSON style (indented or compact) the file already has:
    unlike `Notebook.save()`/`deckz labs fmt`, this doesn't force deckz's
    canonical style, so a repo that hasn't run `deckz labs fmt` yet still
    gets a minimal diff.

    Args:
        path: Path to the `.ipynb` file to normalize.
        solution_heading: The heading text marking a cell to collapse.
        dry_run: Report whether the notebook would change, without writing \
            it.

    Returns:
        True if the notebook was (or, with `dry_run`, would be) changed.
    """
    raw = path.read_text(encoding="utf-8")
    indented = raw.startswith("{\n")
    notebook = json.loads(raw)

    collapsed_changed = sync_collapsed_sections(
        notebook, heading=solution_heading, force=True
    )
    colab_metadata = notebook.setdefault("metadata", {}).setdefault("colab", {})
    ai_changed = not colab_metadata.get("generative_ai_disabled")

    if not (collapsed_changed or ai_changed):
        return False

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
