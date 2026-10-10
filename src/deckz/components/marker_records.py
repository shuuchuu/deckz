"""What each Typst compilation records of its document's metadata markers.

deckz reads a few Typst metadata markers in built documents: its own frame
markers (`frame_markers`), and the theme's shrunk frames and tables
(`GlobalSettings.overflow_marker_label`, `table_marker_label`). Querying a
document compiles it, as long as building it, so the compilation that builds
it queries them too, for a few milliseconds, and records them next to its
PDF: `<main>.markers.json`, each label's values in document order. Readers
use the record while it's at least as new as the PDF (`recorded`), and fall
back to a query of their own for a build no compilation recorded.
"""

import json
from collections.abc import Iterable
from pathlib import Path


def record_path(main: Path) -> Path:
    """Where compiling `main` records its markers.

    Returns:
        `<main's stem>.markers.json` next to it.
    """
    return main.with_name(f"{main.stem}.markers.json")


def selector(labels: Iterable[str]) -> str:
    """A Typst selector for every metadata marker with one of `labels`.

    Returns:
        Typst code, for `typst.Compiler.query`.
    """
    first, *rest = labels
    return f"selector(<{first}>)" + "".join(f".or(<{label}>)" for label in rest)


def write(main: Path, labels: Iterable[str], elements: str | None) -> None:
    """Record the markers of `main`'s last compilation.

    Args:
        main: The compiled main file.
        labels: Every label queried, recorded even when no marker has it.
        elements: Typst's JSON answer to `selector(labels)` (elements with \
            their `label` and `value`); None if the query failed, which \
            removes any older record.
    """
    record = record_path(main)
    if elements is None:
        record.unlink(missing_ok=True)
        return
    markers: dict[str, list[object]] = {label: [] for label in labels}
    for element in json.loads(elements):
        label = element.get("label", "").strip("<>")
        if label in markers:
            markers[label].append(element.get("value"))
    partial = record.with_name(f".{record.name}.partial")
    partial.write_text(json.dumps(markers), encoding="utf8")
    partial.replace(record)


def recorded(main: Path, label: str) -> list | None:
    """The `label` markers the last compilation of `main` recorded.

    Returns:
        Their values, or None when there's no record of `label` as new as \
        `main`'s PDF.
    """
    record = record_path(main)
    try:
        if record.stat().st_mtime_ns < main.with_suffix(".pdf").stat().st_mtime_ns:
            return None
        markers = json.loads(record.read_text(encoding="utf8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return markers.get(label)
