"""Assign IDs to lab notebooks that don't have one yet.

A notebook's public ID is stored in its own metadata (the `labs.id_metadata_key`
setting, `metadata.shuuchuu.id` by default), so the notebook can move freely
under the configured notebooks directory without breaking its published link
(see `deckz labs publish`). It is spelled out from where the notebook sits
when it gets its ID, since Colab shows the published file name as the
browser tab's title.
"""

import json
import re
from collections import defaultdict
from functools import partial
from itertools import product
from pathlib import Path
from typing import Any

from ..exceptions import LabIdConflictError
from .notebook import canonical_dump


def _get_metadata_id(metadata: dict[str, Any], key: str) -> str | None:
    value: Any = metadata
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value if isinstance(value, str) else None


def _set_metadata_id(metadata: dict[str, Any], key: str, lab_id: str) -> None:
    *parents, leaf = key.split(".")
    node = metadata
    for part in parents:
        node = node.setdefault(part, {})
    node[leaf] = lab_id


def lab_section(lab_dir: Path, content_dir: Path) -> str:
    """The content section a lab directory (relative to the notebooks dir) belongs to.

    Returns:
        The longest prefix of `lab_dir`'s path naming a section in \
        `content_dir` (a directory holding a `.yml` of its own name), or \
        `lab_dir`'s whole path if none does.
    """
    parts = lab_dir.parts
    for length in range(len(parts), 0, -1):
        section_dir = content_dir.joinpath(*parts[:length])
        if (section_dir / f"{parts[length - 1]}.yml").exists():
            return "/".join(parts[:length])
    return "/".join(parts)


def _lab_id_base(lab_dir: Path, labs: set[Path], content_dir: Path) -> str:
    """The kebab-case name identifying a lab directory.

    It is its section's name, plus the lab's own name (minus a leading
    repeat of the section's last word) when the section has several labs. A
    section is named by the shortest tail of its path that no other section
    with labs shares.

    Returns:
        The base of the IDs of the lab's notebooks.
    """
    sections = {lab_section(other, content_dir) for other in labs}
    section = lab_section(lab_dir, content_dir)
    parts = section.split("/")
    tail = parts
    for length in range(1, len(parts) + 1):
        tail = parts[-length:]
        if all(
            other == section or other.split("/")[-length:] != tail for other in sections
        ):
            break
    base = "-".join(tail)
    if sum(lab_section(other, content_dir) == section for other in labs) == 1:
        return base
    name = lab_dir.name.removeprefix(f"{parts[-1]}-")
    return f"{base}-{name}"


def lab_id(path: Path, notebooks_dir: Path, labs: set[Path], content_dir: Path) -> str:
    """The ID a notebook (`<notebooks_dir>/<lab>/<type>-<lang>.ipynb`) gets.

    Returns:
        `<lab base>-<type>-<lang>`, e.g. `nn-cnn-image-segmentation-keras-demo-fr`.
    """
    lab_dir = path.parent.relative_to(notebooks_dir)
    return f"{_lab_id_base(lab_dir, labs, content_dir)}-{path.stem}"


def _dump_like(notebook: dict[str, Any], original: str) -> str:
    """Serialize `notebook` in the JSON style of `original` (Colab's or Jupyter's).

    Returns:
        The JSON text, in the first style that reproduces `original` exactly, \
        or in deckz's canonical style if none does.
    """
    original_data = json.loads(original)
    layouts = ((1, None), (2, None), (None, (",", ":")))
    for (indent, separators), ensure_ascii, end in product(
        layouts, (False, True), ("", "\n")
    ):
        dump = partial(
            json.dumps, indent=indent, separators=separators, ensure_ascii=ensure_ascii
        )
        if dump(original_data) + end == original:
            return dump(notebook) + end
    return canonical_dump(notebook)


def assign_ids(
    notebooks_dir: Path,
    content_dir: Path,
    *,
    id_metadata_key: str = "shuuchuu.id",
    id_pattern: str = r"[a-z0-9]+(-[a-z0-9]+)*",
    dry_run: bool = False,
) -> list[tuple[str, Path]]:
    """Give every lab notebook without a published ID a new one.

    Args:
        notebooks_dir: Root directory the notebooks are found under.
        content_dir: Root of the shared content, to detect section boundaries.
        id_metadata_key: Dotted metadata path the ID lives at.
        id_pattern: Pattern an existing ID must match (checked on already \
            assigned IDs; a newly assigned one is always built from path \
            components and so matches the default pattern already).
        dry_run: Report the IDs that would be assigned, without writing them.

    Returns:
        `(id, path)` for every notebook a new ID was (or, with `dry_run`, \
        would be) assigned to.

    Raises:
        LabIdConflictError: If an existing ID is used by several notebooks, \
            an existing ID doesn't match `id_pattern`, or a newly computed \
            ID is already taken.
    """
    valid_id = re.compile(id_pattern)
    ids: dict[str, list[Path]] = defaultdict(list)
    missing: list[Path] = []
    for path in sorted(notebooks_dir.rglob("*.ipynb")):
        metadata = json.loads(path.read_text(encoding="utf-8"))["metadata"]
        existing = _get_metadata_id(metadata, id_metadata_key)
        if existing:
            ids[existing].append(path)
        else:
            missing.append(path)

    if duplicated := {i: paths for i, paths in ids.items() if len(paths) > 1}:
        details = "; ".join(
            f"{i!r} in {', '.join(str(p) for p in paths)}"
            for i, paths in duplicated.items()
        )
        msg = f"duplicate notebook IDs, remove the metadata from the copies: {details}"
        raise LabIdConflictError(msg)

    if invalid := {i: p[0] for i, p in ids.items() if not valid_id.fullmatch(i)}:
        details = "; ".join(f"{i!r} in {p}" for i, p in invalid.items())
        msg = f"notebook ID doesn't match {id_pattern!r}: {details}"
        raise LabIdConflictError(msg)

    labs = {p.parent.relative_to(notebooks_dir) for p in notebooks_dir.rglob("*.ipynb")}
    assigned: list[tuple[str, Path]] = []
    for path in missing:
        new_id = lab_id(path, notebooks_dir, labs, content_dir)
        if new_id in ids:
            msg = f"ID {new_id!r} for {path} is already taken by {ids[new_id][0]}"
            raise LabIdConflictError(msg)
        ids[new_id].append(path)
        assigned.append((new_id, path))
        if not dry_run:
            original = path.read_text(encoding="utf-8")
            notebook = json.loads(original)
            _set_metadata_id(notebook["metadata"], id_metadata_key, new_id)
            path.write_text(_dump_like(notebook, original), encoding="utf-8")
    return assigned
