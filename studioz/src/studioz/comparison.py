"""Before/after: which frames of a deck changed since its baseline.

Frames are matched by title, in order (`difflib`), so that a frame inserted
or removed doesn't shift every comparison after it; a matched pair changed
if its pages look different. Looks are compared on the pages turned into
small grayscale images (poppler's `pdftoppm`, 0.2 s for 85 pages), all but
their bottom right corner, where themes number the frames (Beamer's and
slides' do): inserting a frame renumbers every one after it.

Only frame pages are compared: the title page, outline and dividers follow
from the deck's structure.
"""

import hashlib
import subprocess
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from deckz.analyzing.frames import Frame

_DPI = "40"
# The corner left out, as fractions of the page's height and width.
_COUNTER_TOP = 0.9
_COUNTER_LEFT = 0.85

Kind = Literal["changed", "new", "removed"]


@dataclass(frozen=True)
class Row:
    kind: Kind
    title: str
    before: int | None
    """Its page in the baseline, None if new."""
    after: int | None
    """Its page now, None if removed."""
    file: str | None = None
    """Its source now."""
    line: int | None = None
    before_title: str | None = None
    """Its title in the baseline, when it was another one (retitled, or \
    another frame in its place)."""


@dataclass(frozen=True)
class Comparison:
    rows: tuple[Row, ...]
    """The frames that differ, in the deck's order."""
    unchanged: int

    def count(self, kind: Kind) -> int:
        return sum(row.kind == kind for row in self.rows)


def _signature(pgm: bytes) -> str:
    """A digest of a binary PGM image, its bottom right corner left out.

    Returns:
        Its hex digest.

    Raises:
        ValueError: If `pgm` isn't one, as `pdftoppm -gray` writes them.
    """
    magic, size, depth, pixels = pgm.split(b"\n", 3)
    if magic != b"P5" or depth != b"255":
        msg = "not an 8-bit binary PGM image"
        raise ValueError(msg)
    width, height = map(int, size.split())
    masked = bytearray(pixels[: width * height])
    left = int(width * _COUNTER_LEFT)
    for row in range(int(height * _COUNTER_TOP), height):
        start = row * width
        masked[start + left : start + width] = b"\xff" * (width - left)
    return hashlib.sha1(masked, usedforsecurity=False).hexdigest()


@lru_cache(maxsize=16)
def _signatures(pdf: Path, _mtime: int, _size: int) -> tuple[str, ...]:
    with TemporaryDirectory(prefix="studioz-pages-") as directory:
        subprocess.run(
            ["pdftoppm", "-gray", "-r", _DPI, str(pdf), f"{directory}/p"],
            capture_output=True,
            check=True,
        )
        # Numbered with as many digits as the last page needs.
        pages = sorted(Path(directory).glob("p-*.pgm"))
        return tuple(_signature(page.read_bytes()) for page in pages)


def signatures(pdf: Path) -> tuple[str, ...]:
    """What each page of `pdf` looks like, in short.

    It runs poppler's `pdftoppm`: OSError if it's missing, \
    `subprocess.CalledProcessError` if it fails on `pdf`.

    Returns:
        Each page's signature, equal for pages that look the same but for \
        their number.
    """
    stat = pdf.stat()
    return _signatures(pdf, stat.st_mtime_ns, stat.st_size)


def compare(
    before: dict[int, str],
    before_signatures: tuple[str, ...],
    after: list[Frame],
    after_signatures: tuple[str, ...],
) -> Comparison:
    """The frames that changed from `before` to `after`.

    Args:
        before: The baseline's frame pages and their titles.
        before_signatures: Each page of the baseline's PDF's signature.
        after: The frames now.
        after_signatures: Each page of their PDF's signature.

    Returns:
        The frames changed (same title, different looks; a frame retitled, \
        or replaced by one frame, in place counts as changed), new, and \
        removed, in order.
    """
    old = sorted(before.items())
    matcher = SequenceMatcher(
        None, [title for _, title in old], [frame.title for frame in after], False
    )
    rows: list[Row] = []
    unchanged = 0

    def looks(signatures: tuple[str, ...], page: int) -> str | None:
        return signatures[page - 1] if page <= len(signatures) else None

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        pairs = list(zip(old[i1:i2], after[j1:j2], strict=False))
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for (page, title), frame in pairs:
                if looks(before_signatures, page) == looks(
                    after_signatures, frame.page
                ):
                    unchanged += 1
                else:
                    rows.append(
                        Row(
                            "changed",
                            frame.title,
                            page,
                            frame.page,
                            frame.file,
                            frame.line,
                            title if title != frame.title else None,
                        )
                    )
            continue
        rows.extend(Row("removed", title, page, None) for page, title in old[i1:i2])
        rows.extend(
            Row("new", frame.title, None, frame.page, frame.file, frame.line)
            for frame in after[j1:j2]
        )
    return Comparison(tuple(rows), unchanged)
