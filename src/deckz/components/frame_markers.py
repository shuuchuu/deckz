"""Frame markers: which content file each page of a built deck comes from.

Before a deck's Markdown fragment is converted to Typst, `FrameMarkingConverter`
adds an invisible `<deckz-frame>` marker right after each `# Title` (a frame).
The marker records the fragment, the heading's index in it, and the page it
lands on. `deckz show frames` (`deckz.analyzing.frames`) queries them in the
built document and maps each one back to its content file and line. A frame
shown on several pages (a presentation's steps) has one marker per page.

Each compilation also records the markers it laid out next to its PDF
(`marker_records`), so that reading them takes no compilation.
"""

import json
import re
from hashlib import sha256
from pathlib import Path

from ..exceptions import DeckzError
from .protocols import MarkdownConverterProtocol

LABEL = "deckz-frame"
"""The markers' Typst label."""

_VERSION = "1"
"""Part of the converter's fingerprint: bump it when the markers change, so \
that every fragment is converted again."""

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def frame_headings(text: str) -> list[tuple[int, str]]:
    """Every frame heading (`# Title`) of a Markdown text, outside code blocks.

    Returns:
        Each heading's line index (from 0) and text after `# `.
    """
    headings = []
    fence = None
    for index, line in enumerate(text.splitlines()):
        if match := _FENCE.match(line):
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif (
                marker[0] == fence[0]
                and len(marker) >= len(fence)
                and (line.strip() == marker)
            ):
                fence = None
            continue
        if fence is None and line.startswith("# "):
            headings.append((index, line[2:]))
    return headings


def mark_frames(text: str, fragment: str) -> str:
    """`text` with a `<deckz-frame>` marker after each frame heading.

    Args:
        text: A rendered Markdown fragment.
        fragment: What the markers name it by (its path).

    Returns:
        The marked text.
    """
    lines = text.splitlines()
    for number, (index, _) in reversed(list(enumerate(frame_headings(text)))):
        value = (
            f"(fragment: {json.dumps(fragment)}, index: {number}, page: here().page())"
        )
        lines[index + 1 : index + 1] = [
            "",
            "```{=typst}",
            f"#context [#metadata({value}) <{LABEL}>]",
            "```",
            "",
        ]
    return "\n".join(lines) + "\n"


class FrameMarkingConverter(MarkdownConverterProtocol):
    """Convert like `inner`, after marking the frames (see the module docstring).

    The fragment itself isn't changed: a marked copy next to it is converted.
    """

    def __init__(self, inner: MarkdownConverterProtocol) -> None:
        self._inner = inner

    def convert(self, source: Path, destination: Path) -> None:
        marked = source.with_name(f".{source.stem}.frames{source.suffix}")
        marked.write_text(
            mark_frames(source.read_text(encoding="utf8"), str(source)),
            encoding="utf8",
        )
        try:
            self._inner.convert(marked, destination)
        except DeckzError as error:
            # Name the fragment, not its marked copy.
            raise DeckzError(str(error).replace(marked.name, source.name)) from error
        finally:
            marked.unlink(missing_ok=True)

    def fingerprint(self) -> str:
        return sha256(
            f"{self._inner.fingerprint()}\0frames-{_VERSION}".encode()
        ).hexdigest()
