"""Model classes for parsed decks.

The main class is [`Deck`][deckz.models.deck.Deck]. It's comprised of \
[`Part`][deckz.models.deck.Part]s containing [`Section`][deckz.models.deck.Section]s \
and [`File`][deckz.models.deck.File]s, both of which are \
[`Node`][deckz.models.deck.Node]s and have an \
[`accept`][deckz.models.deck.Node.accept] method to allow visitors to be defined.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass

from ..processing import NodeVisitor
from .scalars import FlavorName, PartName, ResolvedPath, UnresolvedPath


@dataclass
class Node(ABC):
    """Node in a section or part.

    A node is anything that can be included in a [`Part`][deckz.models.deck.Part] or a \
    [`Section`][deckz.models.deck.Section]: it can be either a \
    [`Section`][deckz.models.deck.Section] or a [`File`][deckz.models.deck.File].
    """

    title: str | None
    unresolved_path: UnresolvedPath
    # resolved_path and parsing_error could benefit from a refactoring using something
    # like Either because we cannot have both a ResolvedPath and a parsing_error at the
    # same time.
    resolved_path: ResolvedPath
    parsing_error: str | None

    @abstractmethod
    def accept[**P, T](
        self, visitor: NodeVisitor[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        """Dispatch method for visitors.

        Args:
            visitor: The visitor asking for the dispatch
            args: Arguments to send back to the visitor untouched
            kwargs: Keyword arguments to send back to the visitor untouched

        Returns:
            The return type is the same as the return type of the corresponding \
            [`visit_file`][deckz.processing.NodeVisitor.visit_file] or \
            [`visit_section`][deckz.processing.NodeVisitor.visit_section] method of \
            the visitor.
        """
        raise NotImplementedError


@dataclass
class File(Node):
    """File in a section or part."""

    def accept[**P, T](
        self, visitor: NodeVisitor[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        """Dispatch method for visitors.

        Args:
            visitor: The visitor asking for the dispatch
            args: Arguments to send back to the visitor untouched
            kwargs: Keyword arguments to send back to the visitor untouched

        Returns:
            The return type is the same as the return type of the \
            [`visit_file`][deckz.processing.NodeVisitor.visit_file] method of the \
            visitor.
        """
        return visitor.visit_file(self, *args, **kwargs)


@dataclass
class Section(Node):
    """Section in a section or part."""

    flavor: FlavorName
    """Name of the flavor of the section."""

    nodes: list[Node]
    """Nodes included in the section."""

    def accept[**P, T](
        self, visitor: NodeVisitor[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        """Dispatch method for visitors.

        Args:
            visitor: The visitor asking for the dispatch
            args: Arguments to send back to the visitor untouched
            kwargs: Keyword arguments to send back to the visitor untouched

        Returns:
            The return type is the same as the return type of the \
            [`visit_section`][deckz.processing.NodeVisitor.visit_section] method of \
            the visitor.
        """
        return visitor.visit_section(self, *args, **kwargs)


@dataclass
class Part:
    """Part in a deck."""

    title: str | None
    """Title of the part."""

    nodes: list[Node]
    """Nodes included in the part."""


@dataclass
class Deck:
    """Top of the hierarchy for deck parsing."""

    name: str
    """The name of the deck. Will be a part of the output file name."""

    parts: dict[PartName, Part]
    """Parts included in the deck."""

    def filter(self, whitelist: Iterable[PartName]) -> None:
        """Filter out the parts that don't have their name listed in `whitelist`.

        Args:
            whitelist: Parts to keep.

        Raises:
            ValueError: Raised if an element of `whitelist` matches no part name in \
                the deck.
        """
        if frozenset(whitelist).difference(self.parts):
            msg = "provided whitelist has part names not in the deck"
            raise ValueError(msg)
        to_remove = frozenset(self.parts).difference(whitelist)
        for part_name in to_remove:
            del self.parts[part_name]
