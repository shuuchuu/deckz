"""Search shared sections by keyword.

Understands each section's title/frame structure instead of grepping raw file \
content.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from re import MULTILINE
from re import compile as re_compile
from typing import TYPE_CHECKING

from ..models import Deck, FlavorName, Lang, ResolvedPath, is_lang_map
from ..utils import load_yaml, shared_section_ids

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings

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
    for part_deps in deps.values():
        paths.update(ref.resolved_path for ref in part_deps)
    return paths


def _section_flavor_deck(
    settings: "GlobalSettings", section: str, flavor: FlavorName, lang: Lang = "fr"
) -> Deck:
    from ..components.factory import GlobalSettingsFactory

    return (
        GlobalSettingsFactory(settings)
        .shared_parser(lang)
        .from_section(section, flavor)
    )


def section_files(
    settings: "GlobalSettings",
    section: str,
    flavor: FlavorName,
    lang: Lang = "fr",
) -> set[ResolvedPath]:
    """Resolved absolute file paths a shared section+flavor includes.

    Recurses into subsections, exactly like deckz would when building a deck \
    that includes `$<section>@<flavor>`.

    Args:
        settings: Settings of the repository.
        section: Shared/content-relative section id, e.g. "python/basics".
        flavor: Flavor to resolve.
        lang: Language to resolve the files in.

    Returns:
        The set of resolved file paths.
    """
    return resolved_files(_section_flavor_deck(settings, section, flavor, lang))


@dataclass(frozen=True)
class SectionTitleMatch:
    """A section whose yml `title` or `default_titles` matched a keyword."""

    section: str
    """Shared/content-relative section id, e.g. "python/basics"."""

    title: str
    """The matching title."""


@dataclass(frozen=True)
class FrameTitleMatch:
    """A frame whose title matched a keyword."""

    section: str
    """Shared/content-relative id of the section owning the file, e.g. \
    "python/basics". Check its yml for the flavor(s) that include `file`."""

    file: Path
    """Absolute path of the `.md` file containing the frame."""

    frame_title: str
    """The matching frame title."""


def _matches(text: str, keywords: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _display_text(value: object, lang: Lang) -> str | None:
    """The `lang` text of a raw (unresolved) title value, a string or a lang-map.

    A lang-map missing `lang` falls back to its fr text, then to any text.

    Returns:
        The extracted text, or None if `value` isn't title-shaped.
    """
    if isinstance(value, str):
        return value
    if is_lang_map(value):
        return value.get(lang) or value.get("fr") or next(iter(value.values()), None)
    return None


def _frame_title_matches(
    section_dir: Path, section: str, keywords: Sequence[str], lang: Lang
) -> list[FrameTitleMatch]:
    matches = []
    files_dir = section_dir / "en" if lang == "en" else section_dir
    for path in sorted(files_dir.glob("*.md")):
        text = path.read_text(encoding="utf8")
        for match in _MARKDOWN_HEADING.finditer(text):
            frame_title = match.group(1)
            if frame_title and _matches(frame_title, keywords):
                matches.append(FrameTitleMatch(section, path, frame_title))
    return matches


def search_sections(
    shared_content_dir: Path, keywords: Sequence[str], lang: Lang = "fr"
) -> tuple[list[SectionTitleMatch], list[FrameTitleMatch]]:
    """Search shared sections for KEYWORDS (OR'd, case-insensitive substring).

    Looks only at each section's `.yml` `title`/`default_titles` values and \
    each of its own `.md` files' headings (`#`/`##`/...) -- never at frame \
    bodies, code or comments. Under "en", titles resolve to their English \
    text and headings are read from the section's `en/` files instead.

    Args:
        shared_content_dir: Path to the shared content directory.
        keywords: Keywords to search for.
        lang: Language to search titles and headings in.

    Returns:
        The yml-title matches and the frame-title matches, each sorted by \
        section then match.
    """
    section_matches: list[SectionTitleMatch] = []
    frame_matches: list[FrameTitleMatch] = []
    for section in shared_section_ids(shared_content_dir):
        section_dir = shared_content_dir / section
        yml_path = section_dir / f"{section_dir.name}.yml"

        data = load_yaml(yml_path) or {}
        raw_titles = [data.get("title"), *(data.get("default_titles") or {}).values()]
        titles = [t for raw in raw_titles if (t := _display_text(raw, lang))]
        for title in titles:
            if _matches(title, keywords):
                section_matches.append(SectionTitleMatch(section, title))

        frame_matches.extend(_frame_title_matches(section_dir, section, keywords, lang))
    return section_matches, frame_matches
