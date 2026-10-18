"""Find a built handout's shrunk frames, wrapped tables and lines, with their sources.

The target repo's Typst theme emits one `settings.overflow_marker_label`
metadata marker per frame it had to shrink to fit the page (`ratio`, `page`),
one `settings.table_marker_label` marker per table it laid out (`page`,
`wrap`: the table's height over its height with no cell wrapped, as a
percentage, and `overflow`: whether its longest words alone are wider than the
frame), and one `settings.line_marker_label` marker per page whose header or
footer line wraps (`page`, `line`, `text`, `ratio`: its width over its room,
`fix`: what to shorten, `frame`: whether that's in the page's frame). deckz's
business is only to query and report them, not to produce them: the
shrinking and the layouts stay the theme's. This reads the handout already
built by `deckz run --handout` (or a `deckz run file`/`deckz run section`
preview) -- the markers its compilation recorded
(`deckz.components.marker_records`), and each page's frame, content file and
line (`deckz.analyzing.frames`) -- it doesn't build anything itself.

A build no compilation recorded (an older deckz's) is queried instead, a
whole compilation; one with no frame markers either is matched by title:
every page's frame title (the line under the header's breadcrumb, from
poppler's `pdftotext`) against the `# Title` headings among the content
fragments the build included. A frame is one page, so the n-th page with a
title shared by several frames (e.g. "Quiz") is the n-th heading with that
title. When the counts disagree (a heading rendered on no page, or a PDF
title differing from its heading's text), every candidate source is listed.
"""

import re
import subprocess
from collections.abc import Collection
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..components import marker_records
from ..exceptions import DeckzError
from ..models import lang_dir
from ..utils import deck_name_from_dir
from .frames import frames, query_markers

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings
    from ..models import Lang

_INCLUDE = re.compile(r'^#include "(.+)\.typ"$', re.MULTILINE)


@dataclass(frozen=True)
class _Located:
    marker: dict
    page: int
    title: str
    sources: tuple[str, ...]
    line: int | None


@dataclass(frozen=True)
class ShrunkFrame:
    """One handout frame the Typst theme had to shrink to fit the page."""

    ratio: str
    page: int
    title: str
    sources: tuple[str, ...]
    """The content file(s) building this frame, or `("?",)` if none matched."""
    line: int | None = None
    """The frame's `# Title` line in its only source, if known."""


@dataclass(frozen=True)
class WrappedLine:
    """A header or footer line that wraps, on one or more handout pages."""

    line: str
    """Which line, as the theme names it (e.g. `footer`)."""
    text: str
    """Its plain text."""
    ratio: str
    """Its width over its room, on its worst page (above `"100%"`)."""
    pages: tuple[int, ...]
    """Every page where it wraps, in order."""
    fix: str
    """What to shorten, as the theme words it."""
    source: str | None = None
    """`<content file>:<line>` of its frame's `# Title`, for a line whose fix \
    is in the frame (the marker's `frame`, e.g. the frame title), if known."""


@dataclass(frozen=True)
class WrappedTable:
    """One handout table, with how much its cells wrap."""

    wrap: str
    """Its height over its height with no cell wrapped (`"100%"` when none does)."""
    overflow: bool
    """Whether its longest words alone are wider than the frame."""
    page: int
    title: str
    sources: tuple[str, ...]
    """The content file(s) building its frame, or `("?",)` if none matched."""
    line: int | None = None
    """Its frame's `# Title` line in its only source, if known."""


def _normalize(title: str) -> str:
    # A heading's or a PDF line's text, without Markdown markup; split() also
    # drops the non-breaking spaces of French typography.
    title = re.sub(r"\{[^}]*\}\s*$", "", title)
    title = re.sub(r"[`*_\\]", "", title.replace("\\ ", " "))
    # pandoc's smart dashes, as the PDF shows them.
    title = title.replace("---", "\u2014").replace("--", "\u2013")
    return " ".join(title.split())


def _page_titles(pdf: Path, known: Collection[str] = ()) -> list[str]:
    text = subprocess.run(
        ["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True
    ).stdout
    titles = []
    for page in text.split("\f"):
        lines = [line for line in page.splitlines() if line.strip()]
        # A frame's first line is its header's breadcrumb (part ⋅ section, or
        # a single level), its second its title; a divider, which may show a
        # section titled like a frame, has no "⋅" and no `known` heading next.
        frame = len(lines) > 1 and ("⋅" in lines[0] or _normalize(lines[1]) in known)
        titles.append(_normalize(lines[1]) if frame else "")
    return titles


def _headings(
    build_dir: Path,
    main_typ: Path,
    *,
    current_dir: Path,
    local_content_dir: Path,
    content_dir: Path,
    git_dir: Path,
) -> dict[str, list[str]]:
    # The build directory keeps fragments of files the deck no longer
    # includes: only read those #include'd, as "<path>-<hash>.typ" next to
    # "<path>-<hash>.md" (the still-Markdown render, before pandoc).
    included = _INCLUDE.findall(main_typ.read_text(encoding="utf8"))
    local_prefix = local_content_dir.relative_to(current_dir).as_posix()
    found: dict[str, list[str]] = {}
    for fragment in included:
        markdown = build_dir / f"{fragment}.md"
        if not markdown.exists():
            continue
        name = fragment + ".md"
        is_local = name == local_prefix or name.startswith(f"{local_prefix}/")
        where = (
            (current_dir / name).relative_to(git_dir)
            if is_local
            else (content_dir / name).relative_to(git_dir)
        )
        for line in markdown.read_text(encoding="utf8").splitlines():
            if line.startswith("# "):
                found.setdefault(_normalize(line[2:]), []).append(where.as_posix())
    return found


def _handout(settings: "DeckSettings", lang: "Lang") -> tuple[Path, Path, Path]:
    """The built handout's files.

    Returns:
        Its build directory, main Typst file and PDF.

    Raises:
        DeckzError: If the deck's handout hasn't been built.
    """
    paths = settings.paths
    name = deck_name_from_dir(paths.current_dir)
    build_dir = lang_dir(paths.build_dir, lang) / f"{name}-handout"
    main_typ = build_dir / f"{name}-handout.typ"
    pdf = lang_dir(paths.pdf_dir, lang) / f"{name}-handout.pdf"
    if not pdf.is_file():
        msg = (
            f"{pdf} is missing: build the deck's handout first "
            f"(`deckz run --handout --lang {lang}`)"
        )
        raise DeckzError(msg)
    return build_dir, main_typ, pdf


def _locate(
    settings: "DeckSettings", label: str, *, lang: "Lang", query: bool
) -> list[_Located]:
    """Every `label` marker of the built handout, with its frame and sources.

    Returns:
        One `_Located` per marker, in document order.

    Raises:
        DeckzError: If the deck's handout hasn't been built, or, without \
            `query`, if its build recorded no markers.
    """
    build_dir, main_typ, pdf = _handout(settings, lang)
    markers = marker_records.recorded(main_typ, label)
    if markers is None:
        if not query:
            msg = f"{pdf}'s build recorded no markers: build it again with this deckz"
            raise DeckzError(msg)
        markers = query_markers(settings, main_typ, label)
    if not markers:
        return []
    try:
        by_page = {frame.page: frame for frame in frames(settings, pdf, query=query)}
    except DeckzError:
        # Built before deckz marked frames.
        return _locate_by_title(settings, markers, build_dir, main_typ, pdf)
    located = []
    for marker in markers:
        frame = by_page.get(marker["page"])
        located.append(
            _Located(
                marker=marker,
                page=marker["page"],
                title=_normalize(frame.title) if frame else "",
                sources=(frame.file or "?",) if frame else ("?",),
                line=frame.line if frame else None,
            )
        )
    return located


def _locate_by_title(
    settings: "DeckSettings",
    markers: list[dict],
    build_dir: Path,
    main_typ: Path,
    pdf: Path,
) -> list[_Located]:
    paths = settings.paths
    sources_of = _headings(
        build_dir,
        main_typ,
        current_dir=paths.current_dir,
        local_content_dir=paths.local_content_dir,
        content_dir=paths.content_dir,
        git_dir=paths.git_dir,
    )
    titles = _page_titles(pdf, set(sources_of))
    located = []
    for marker in markers:
        page = marker["page"]
        title = titles[page - 1]
        sources = sources_of.get(title, ["?"])
        # A frame is one page: the n-th page titled so is the n-th such heading.
        if len(sources) == titles.count(title):
            sources = [sources[titles[: page - 1].count(title)]]
        located.append(
            _Located(
                marker=marker,
                page=page,
                title=title,
                sources=tuple(dict.fromkeys(sources)),
                line=None,
            )
        )
    return located


def _percent(value: str) -> float:
    return float(value.rstrip("%"))


def shrunk_frames(
    settings: "DeckSettings", *, lang: "Lang" = "fr", query: bool = True
) -> list[ShrunkFrame]:
    """Every shrunk frame of `settings`' deck's built handout, worst first.

    Needs `deckz run --handout` (or a `deckz run file`/`deckz run section`
    preview), in `lang`, to have already run: this only reads its
    build output. Without `query`, a build no compilation recorded (an
    older deckz's) is an error rather than compiled again in this process.

    Returns:
        One `ShrunkFrame` per `settings.overflow_marker_label` marker, \
        sorted by `ratio` ascending (most shrunk first). Raises a \
        `DeckzError` if the deck's handout hasn't been built.
    """
    frames = [
        ShrunkFrame(
            ratio=found.marker["ratio"],
            page=found.page,
            title=found.title,
            sources=found.sources,
            line=found.line,
        )
        for found in _locate(
            settings, settings.overflow_marker_label, lang=lang, query=query
        )
    ]
    return sorted(frames, key=lambda frame: _percent(frame.ratio))


def wrapped_tables(
    settings: "DeckSettings", *, lang: "Lang" = "fr", query: bool = True
) -> list[WrappedTable]:
    """Every table of `settings`' deck's built handout, most wrapped first.

    Needs `deckz run --handout` (or a `deckz run file`/`deckz run section`
    preview), in `lang`, to have already run: this only reads its
    build output (see `shrunk_frames` for `query`).

    Returns:
        One `WrappedTable` per `settings.table_marker_label` marker, sorted \
        by `wrap` descending (most wrapped first). Raises a `DeckzError` \
        if the deck's handout hasn't been built.
    """
    tables = [
        WrappedTable(
            wrap=found.marker["wrap"],
            overflow=bool(found.marker.get("overflow", False)),
            page=found.page,
            title=found.title,
            sources=found.sources,
            line=found.line,
        )
        for found in _locate(
            settings, settings.table_marker_label, lang=lang, query=query
        )
    ]
    return sorted(tables, key=lambda table: -_percent(table.wrap))


def wrapped_lines(
    settings: "DeckSettings", *, lang: "Lang" = "fr", query: bool = True
) -> list[WrappedLine] | None:
    """Every header or footer line of the built handout that wraps, worst first.

    Needs the handout already built, in `lang` (see `shrunk_frames`, also
    for `query`). The same line wrapping on several pages (a long section
    title in every breadcrumb of its frames, a long footer on every page) is
    one `WrappedLine`.

    Returns:
        One `WrappedLine` per line and text, sorted by `ratio` descending; \
        None when the handout's build recorded markers but not these (an \
        older deckz's build: build it again), or, without `query`, recorded \
        none. Raises a `DeckzError` if the deck's handout hasn't been built.
    """
    label = settings.line_marker_label
    _, main_typ, pdf = _handout(settings, lang)
    markers = marker_records.recorded(main_typ, label)
    if markers is None:
        if not query or marker_records.recorded_without(main_typ, label):
            return None
        markers = query_markers(settings, main_typ, label)
    by_page = {}
    if any(marker.get("frame") for marker in markers):
        # Built before deckz marked frames: no source, only pages.
        with suppress(DeckzError):
            by_page = {
                frame.page: frame for frame in frames(settings, pdf, query=query)
            }
    grouped: dict[tuple[str, str, str | None], list[dict]] = {}
    for marker in markers:
        frame = by_page.get(marker["page"]) if marker.get("frame") else None
        source = f"{frame.file}:{frame.line}" if frame and frame.file else None
        key = (marker["line"], marker["text"], source)
        grouped.setdefault(key, []).append(marker)
    lines = [
        WrappedLine(
            line=line,
            text=text,
            ratio=max((found["ratio"] for found in group), key=_percent),
            pages=tuple(found["page"] for found in group),
            fix=group[0]["fix"],
            source=source,
        )
        for (line, text, source), group in grouped.items()
    ]
    return sorted(lines, key=lambda line: -_percent(line.ratio))
