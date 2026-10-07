"""Find a built handout's shrunk-to-fit frames and the content file(s) behind them.

The target repo's Typst theme emits one `settings.overflow_marker_label`
metadata marker per frame it had to shrink to fit the page (`ratio`, `page`),
deckz's own business only to query and report, not to produce: the shrinking
mechanism itself stays the theme's. This reads the handout already built by
`deckz run --handout` (or a `deckz run file`/`deckz run section` preview) --
the Typst metadata (`typst.Compiler.query`), every page's frame title (the
line under the header's breadcrumb, from poppler's `pdftotext`), and the
`# Title` heading among the content fragments the build included -- it
doesn't build anything itself.

A frame is one page, so the n-th page with a title shared by several frames
(e.g. "Quiz") is the n-th heading with that title. When the counts disagree
(a heading rendered on no page, or a PDF title differing from its heading's
text), every candidate source is listed.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from ..exceptions import DeckzError
from ..utils import deck_name_from_dir

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings

_INCLUDE = re.compile(r'^#include "(.+)\.typ"$', re.MULTILINE)
_FRAGMENT_HASH = re.compile(r"-[0-9a-f]{16}$")


@dataclass(frozen=True)
class ShrunkFrame:
    """One handout frame the Typst theme had to shrink to fit the page."""

    ratio: str
    page: int
    title: str
    sources: tuple[str, ...]
    """The content file(s) building this frame, or `("?",)` if none matched."""


def _normalize(title: str) -> str:
    # A heading's or a PDF line's text, without Markdown markup; split() also
    # drops the non-breaking spaces of French typography.
    title = re.sub(r"\{[^}]*\}\s*$", "", title)
    title = re.sub(r"[`*_\\]", "", title.replace("\\ ", " "))
    return " ".join(title.split())


def _page_titles(pdf: Path) -> list[str]:
    text = subprocess.run(
        ["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True
    ).stdout
    titles = []
    for page in text.split("\f"):
        lines = [line for line in page.splitlines() if line.strip()]
        # A frame's first line is its header's breadcrumb (part ⋅ section); a
        # divider, which may show a section titled like a frame, has none.
        frame = len(lines) > 1 and "⋅" in lines[0]
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


def shrunk_frames(settings: "DeckSettings") -> list[ShrunkFrame]:
    """Every shrunk frame of `settings`' deck's built handout, worst first.

    Needs `deckz run --handout` (or a `deckz run file`/`deckz run section`
    preview) to have already run: this only reads its build output.

    Returns:
        One `ShrunkFrame` per `settings.overflow_marker_label` marker, \
        sorted by `ratio` ascending (most shrunk first).

    Raises:
        DeckzError: If the deck's handout hasn't been built.
    """
    import typst

    paths = settings.paths
    name = deck_name_from_dir(paths.current_dir)
    build_dir = paths.build_dir / f"{name}-handout"
    main_typ = build_dir / f"{name}-handout.typ"
    pdf = paths.pdf_dir / f"{name}-handout.pdf"
    if not pdf.is_file():
        msg = (
            f"{pdf} is missing: build the deck's handout first (`deckz run --handout`)"
        )
        raise DeckzError(msg)

    label = f"<{settings.overflow_marker_label}>"
    markers = (
        yaml.safe_load(
            typst.Compiler(str(main_typ), root=str(build_dir)).query(
                label, field="value"
            )
        )
        or []
    )
    if not markers:
        return []

    sources_of = _headings(
        build_dir,
        main_typ,
        current_dir=paths.current_dir,
        local_content_dir=paths.local_content_dir,
        content_dir=paths.content_dir,
        git_dir=paths.git_dir,
    )
    titles = _page_titles(pdf)
    frames = []
    for marker in markers:
        page = marker["page"]
        title = titles[page - 1]
        sources = sources_of.get(title, ["?"])
        # A frame is one page: the n-th page titled so is the n-th such heading.
        if len(sources) == titles.count(title):
            sources = [sources[titles[: page - 1].count(title)]]
        frames.append(
            ShrunkFrame(
                ratio=marker["ratio"],
                page=page,
                title=title,
                sources=tuple(dict.fromkeys(sources)),
            )
        )
    return sorted(frames, key=lambda frame: float(frame.ratio.rstrip("%")))
