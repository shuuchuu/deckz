from typing import TYPE_CHECKING, Protocol, TypeVar

from typing_extensions import ParamSpec

# Necessary to avoid circular imports with ..models.deck
if TYPE_CHECKING:
    from ..models import Deck, File, Section

_P = ParamSpec("_P")
_T = TypeVar("_T", covariant=True)


class NodeVisitor(Protocol[_P, _T]):
    def visit_file(self, file: "File", *args: _P.args, **kwargs: _P.kwargs) -> _T: ...
    def visit_section(
        self, section: "Section", *args: _P.args, **kwargs: _P.kwargs
    ) -> _T: ...


class Processor(Protocol[_T]):
    def process(self, deck: "Deck") -> _T: ...
