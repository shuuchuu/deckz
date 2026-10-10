"""Find a built handout's shrunk-to-fit frames and wrapped tables, with their sources.

The target repo's Typst theme emits one `settings.overflow_marker_label`
metadata marker per frame it had to shrink to fit the page (`ratio`, `page`),
and one `settings.table_marker_label` marker per table it laid out (`page`,
`wrap`: the table's height over its height with no cell wrapped, as a
percentage, and `overflow`: whether its longest words alone are wider than the
frame). deckz's business is only to query and report them, not to produce
them: the shrinking and the table layout stay the theme's. This reads the
handout already built by `deckz run --handout` (or a `deckz run file`/`deckz
run section` preview) -- the markers its compilation recorded
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
_FRAGMENT_HASH = re.compile(r"-[0-9a-f]{16}$")


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
        name = _FRAGMENT_HASH.sub("", fragment) + ".md"
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
