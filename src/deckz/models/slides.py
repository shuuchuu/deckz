"""Model classes to define decks for the rendering side of deckz."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Title:
    """Define a title slide and its level.

    The lower the level, the more important the title. Similar to how h1 in HTML is \
    a more important title than h2.
    """

    title: str
    """The title string to display during rendering."""

    level: int
    """The level of the title."""


Content = str
"""Alias to string to denote slide content path."""

TitleOrContent = Title | Content
"""Alias to title or content to denote any slide."""


@dataclass(frozen=True)
class PartSlides:
    """Title and slides comprising a part."""

    title: str | None
    """Title of the part."""

    sections: list[TitleOrContent] = field(default_factory=list)
    """Slides of the part."""
