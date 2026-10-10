"""Which frame, content file and line each page of a built deck PDF shows.

Reads the `<deckz-frame>` markers a deck build puts after each frame heading
(`deckz.components.frame_markers`), by querying the built document: it builds
nothing itself, and needs the PDF built first. Each marker names its fragment
in the build directory and the heading's index there: the fragment's name
gives its content file (the deck's own `content/` or the shared one), and the
heading's index gives the line, as the n-th frame heading of the source file
(by title when Jinja made the counts differ).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from ..components.frame_markers import LABEL, frame_headings
from ..exceptions import DeckzError

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings

_FRAGMENT_HASH = re.compile(r"-[0-9a-f]{16}$")
_ATTRIBUTES = re.compile(r"\s*\{[^}]*\}\s*$")


@dataclass(frozen=True)
class Frame:
    page: int
    title: str
    """The heading's text, as written (Markdown), without attributes."""
    file: str | None
    """The content file, relative to the git root; None if not found."""
    line: int | None
    """The heading's line in `file` (from 1); None if not found."""


def frames(settings: "DeckSettings", pdf: Path) -> list[Frame]:
    """Every frame page of `pdf`, a PDF built from `settings`' deck.

    Args:
        settings: The deck's settings.
        pdf: A Typst PDF the deck's build wrote (handout, presentation or \
            print handout, in any language).

    Returns:
        One `Frame` per marked page, in page order; title, divider and \
        outline pages have none.

    Raises:
        DeckzError: If `pdf` or its build isn't there, or was built before \
            deckz marked frames.
    """
    import typst

    paths = settings.paths
    pdf = pdf.resolve()
    try:
        language_dir = pdf.parent.relative_to(paths.pdf_dir.resolve())
    except ValueError:
        msg = f"{pdf} isn't in the deck's PDF directory {paths.pdf_dir}"
        raise DeckzError(msg) from None
    build_dir = paths.build_dir.resolve() / language_dir / pdf.stem
    main = build_dir / f"{pdf.stem}.typ"
    if not pdf.is_file() or not main.is_file():
        msg = f"{pdf} or its build {main} is missing: build it first (`deckz run`)"
        raise DeckzError(msg)
    markers = yaml.safe_load(
        typst.Compiler(
            str(main),
            root=str(build_dir),
            font_paths=[str(path) for path in _font_paths(settings)],
            ignore_system_fonts=settings.typst_ignore_system_fonts,
        ).query(f"<{LABEL}>", field="value")
    )
    if not markers:
        msg = f"{pdf} has no frame markers: build it again with this deckz"
        raise DeckzError(msg)
    sources: dict[Path, tuple[str | None, list[tuple[int, str]], list[int | None]]] = {}
    found = []
    for marker in markers:
        fragment = Path(marker["fragment"])
        if fragment not in sources:
            sources[fragment] = _source(settings, build_dir, fragment)
        file, headings, lines = sources[fragment]
        index = marker["index"]
        title = _ATTRIBUTES.sub("", headings[index][1]) if index < len(headings) else ""
        line = lines[index] if index < len(lines) else None
        found.append(Frame(marker["page"], title, file, line))
    return sorted(found, key=lambda frame: frame.page)


def _font_paths(settings: "DeckSettings") -> list[Path]:
    paths = settings.paths
    return [
        paths.git_dir
        / path.format(
            git_dir=paths.git_dir,
            assets_dir=paths.assets_dir,
            templates_dir=paths.templates_dir,
        )
        for path in settings.typst_font_paths
    ]


def _source(
    settings: "DeckSettings", build_dir: Path, fragment: Path
) -> tuple[str | None, list[tuple[int, str]], list[int | None]]:
    """A fragment's content file, its frame headings, and their source lines.

    Returns:
        The content file relative to the git root (None if not found), the \
        fragment's frame headings, and each one's line in the content file.
    """
    headings = frame_headings(fragment.read_text(encoding="utf8"))
    paths = settings.paths
    try:
        relative = fragment.relative_to(build_dir)
    except ValueError:
        return None, headings, []
    name = relative.parent / (_FRAGMENT_HASH.sub("", relative.stem) + ".md")
    local_prefix = paths.local_content_dir.relative_to(paths.current_dir)
    source = (
        paths.current_dir / name
        if name.is_relative_to(local_prefix)
        else paths.content_dir / name
    )
    if not source.is_file():
        return None, headings, []
    own = frame_headings(source.read_text(encoding="utf8"))
    if len(own) == len(headings):
        lines: list[int | None] = [index + 1 for index, _ in own]
    else:
        # Jinja added or removed frames: match by title.
        by_title = {title: index + 1 for index, title in reversed(own)}
        lines = [by_title.get(title) for _, title in headings]
    return source.relative_to(paths.git_dir).as_posix(), headings, lines
