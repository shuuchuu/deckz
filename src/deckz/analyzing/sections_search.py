"""Search shared sections by keyword.

Understands each section's title/frame structure instead of grepping raw file \
content.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from re import MULTILINE, Pattern
from re import compile as re_compile

from ..models import Deck, FlavorName, ResolvedPath, is_lang_map
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


def resolved_files(deck: Deck) -> set[ResolvedPath]:
    """Resolved absolute file paths a deck includes, flattened across parts.

    Returns:
        The set of resolved file paths.
    """
    from ..components.deck_builder import PartDependenciesNodeVisitor

    deps = PartDependenciesNodeVisitor().process(deck)
    paths: set[ResolvedPath] = set()
    for part_paths in deps.values():
        paths.update(part_paths)
    return paths


def _section_flavor_deck(
    shared_latex_dir: Path,
    file_extensions: Iterable[str],
    section: str,
    flavor: FlavorName,
) -> Deck:
    from ..components.parser import Parser

    parser = Parser(
        local_latex_dir=shared_latex_dir,
        shared_latex_dir=shared_latex_dir,
        file_extensions=file_extensions,
    )
    return parser.from_section(section, flavor)


def section_files(
    shared_latex_dir: Path,
    file_extensions: Iterable[str],
    section: str,
    flavor: FlavorName,
) -> set[ResolvedPath]:
    """Resolved absolute file paths a shared section+flavor includes.

    Recurses into subsections, exactly like deckz would when building a deck \
    that includes `$<section>@<flavor>`.

    Args:
        shared_latex_dir: Path to the shared latex directory.
        file_extensions: Extensions to try, in order, when resolving files.
        section: Shared/latex-relative section id, e.g. "python/basics".
        flavor: Flavor to resolve.

    Returns:
        The set of resolved file paths.
    """
    return resolved_files(
        _section_flavor_deck(shared_latex_dir, file_extensions, section, flavor)
    )


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


def _display_text(value: object) -> str | None:
    """The fr text of a raw (unresolved) title value, a plain string or a lang-map.

    Returns:
        The extracted text, or None if `value` isn't title-shaped.
    """
    if isinstance(value, str):
        return value
    if is_lang_map(value):
        return value.get("fr") or next(iter(value.values()), None)
    return None


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
    code or comments.

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

        data = load_yaml(yml_path) or {}
        raw_titles = [data.get("title"), *(data.get("default_titles") or {}).values()]
        titles = [t for raw in raw_titles if (t := _display_text(raw))]
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
