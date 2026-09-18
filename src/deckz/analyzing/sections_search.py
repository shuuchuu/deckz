"""Search shared sections by keyword.

Understands each section's title/frame structure instead of grepping raw file \
content.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from re import MULTILINE, Pattern
from re import compile as re_compile

from ..models import FlavorName
from ..utils import load_yaml

_FRAME_TITLE = re_compile(r"\\begin\{frame\}(?:\[[^]]*\])?\{([^}]*)\}")
_MARKDOWN_HEADING = re_compile(r"^#+[ \t]+(.+?)[ \t]*$", MULTILINE)


def flavor_names(yml_path: Path) -> list[FlavorName]:
    """Flavor names declared in a section's yml, without resolving anything.

    Returns:
        The section's flavor names, in declaration order.
    """
    data = load_yaml(yml_path) or {}
    return [FlavorName(flavor["name"]) for flavor in data.get("flavors", [])]


@dataclass(frozen=True)
class SectionTitleMatch:
    """A section whose yml `title` or `default_titles` matched a keyword."""

    section: str
    """Shared/latex-relative section id, e.g. "python/basics"."""

    title: str
    """The matching title."""


@dataclass(frozen=True)
class FrameTitleMatch:
    """A frame whose title matched a keyword."""

    section: str
    """Shared/latex-relative id of the section owning the file, e.g. \
    "python/basics". Check its yml for the flavor(s) that include `file`."""

    file: Path
    """Absolute path of the `.tex` or `.md` file containing the frame."""

    frame_title: str
    """The matching frame title."""


def _matches(text: str, keywords: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _frame_title_matches(
    section_dir: Path,
    glob: str,
    title_re: Pattern[str],
    section: str,
    keywords: Sequence[str],
) -> list[FrameTitleMatch]:
    matches = []
    for path in sorted(section_dir.glob(glob)):
        text = path.read_text(encoding="utf8")
        for match in title_re.finditer(text):
            frame_title = match.group(1)
            if frame_title and _matches(frame_title, keywords):
                matches.append(FrameTitleMatch(section, path, frame_title))
    return matches


def search_sections(
    shared_latex_dir: Path, keywords: Sequence[str]
) -> tuple[list[SectionTitleMatch], list[FrameTitleMatch]]:
    r"""Search fr shared sections for KEYWORDS (OR'd, case-insensitive substring).

    Looks only at each section's `.yml` `title`/`default_titles` values, each \
    of its own `.tex` files' frame titles (`\begin{frame}{...}`), and each of \
    its own `.md` files' headings (`#`/`##`/...) -- never at frame bodies, \
    code or comments. Skips `en/` sections and files: this is meant to find \
    fr content to reuse or extend.

    Args:
        shared_latex_dir: Path to the shared latex directory.
        keywords: Keywords to search for.

    Returns:
        The yml-title matches and the frame-title matches, each sorted by \
        section then match.
    """
    section_matches: list[SectionTitleMatch] = []
    frame_matches: list[FrameTitleMatch] = []
    for yml_path in sorted(shared_latex_dir.rglob("*.yml")):
        section_dir = yml_path.parent
        if section_dir.name != yml_path.stem:
            continue
        section = section_dir.relative_to(shared_latex_dir).as_posix()
        if "en" in section_dir.relative_to(shared_latex_dir).parts:
            continue

        data = load_yaml(yml_path) or {}
        titles = [t for t in (data.get("title"),) if t]
        titles.extend((data.get("default_titles") or {}).values())
        for title in titles:
            if _matches(title, keywords):
                section_matches.append(SectionTitleMatch(section, title))

        frame_matches.extend(
            _frame_title_matches(section_dir, "*.tex", _FRAME_TITLE, section, keywords)
        )
        frame_matches.extend(
            _frame_title_matches(
                section_dir, "*.md", _MARKDOWN_HEADING, section, keywords
            )
        )
    return section_matches, frame_matches
