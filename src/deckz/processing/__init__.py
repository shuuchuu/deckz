"""Provide protocols to better type-check deck processing code."""

from typing import TYPE_CHECKING, Protocol

# Necessary to avoid circular imports with ..models.deck
if TYPE_CHECKING:
    from ..models.deck import Deck, File, Section


class NodeVisitor[**P, T](Protocol):
    """Dispatch actions on [`Node`][deckz.models.deck.Node]s."""

    def visit_file(self, file: "File", *args: P.args, **kwargs: P.kwargs) -> T:
        """Dispatched method for [`File`][deckz.models.deck.File]s."""
        ...

    def visit_section(self, section: "Section", *args: P.args, **kwargs: P.kwargs) -> T:
        """Dispatched method for [`Section`][deckz.models.deck.Section]s."""
        ...


class Processor[T](Protocol):
    def process(self, deck: "Deck") -> T:
        """Process a deck."""
        ...
