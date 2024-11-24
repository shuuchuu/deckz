"""Model classes for parsed decks.

The main class is `Deck`. It's comprised of `Part`s containing `Section`s and `File`s, \
both of which are `Node`s and have a `process` method to allow visitors to be defined.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from typing_extensions import ParamSpec

from ..processing import NodeVisitor

__all__ = ["Deck", "File", "Node", "Part", "Section"]

_P = ParamSpec("_P")
_T = TypeVar("_T", covariant=True)


@dataclass
class Node(ABC):
    title: str | None
    logical_path: Path
    path: Path
    parsing_error: str | None

    @abstractmethod
    def accept(
        self, visitor: NodeVisitor[_P, _T], *args: _P.args, **kwargs: _P.kwargs
    ) -> _T:
        raise NotImplementedError


@dataclass
class File(Node):
    def accept(
        self, visitor: NodeVisitor[_P, _T], *args: _P.args, **kwargs: _P.kwargs
    ) -> _T:
        return visitor.visit_file(self, *args, **kwargs)


@dataclass
class Section(Node):
    flavor: str
    children: list[Node]

    def accept(
        self, visitor: NodeVisitor[_P, _T], *args: _P.args, **kwargs: _P.kwargs
    ) -> _T:
        return visitor.visit_section(self, *args, **kwargs)


@dataclass
class Part:
    title: str | None
    nodes: list[Node]


@dataclass
class Deck:
    acronym: str
    parts: dict[str, Part]

    def filter(self, whitelist: Iterable[str]) -> None:
        if frozenset(whitelist).difference(self.parts):
            msg = "provided whitelist has part names not in the deck"
            raise ValueError(msg)
        to_remove = frozenset(self.parts).difference(whitelist)
        for part_name in to_remove:
            del self.parts[part_name]
