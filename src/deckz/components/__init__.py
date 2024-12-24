from abc import abstractmethod
from typing import TYPE_CHECKING

from ..configuring.registry import DeckComponent, GlobalComponent

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from ..configuring.settings import DeckSettings
    from ..models.compilation import CompileResult
    from ..models.deck import Deck
    from ..models.scalars import FlavorName


class Parser(DeckComponent, key="parser"):
    """Build a deck from a definition.

    The definition can be a complete deck definition obtained from a yaml file or a \
    simpler one obtained from a single section or file.
    """

    def __init__(self, local_latex_dir: "Path") -> None:
        self._local_latex_dir = local_latex_dir

    @abstractmethod
    def from_deck_definition(self, deck_definition_path: "Path") -> "Deck":
        """Parse a deck from a yaml definition.

        Args:
            deck_definition_path: Path to the yaml definition. It should be parsable \
                into a [deckz.models.definitions.DeckDefinition][] by Pydantic

        Returns:
            The parsed deck
        """
        raise NotImplementedError

    @abstractmethod
    def from_section(self, section: str, flavor: "FlavorName") -> "Deck":
        raise NotImplementedError

    @abstractmethod
    def from_file(self, latex: str) -> "Deck":
        raise NotImplementedError


class Builder(DeckComponent, key="builder"):
    def __init__(
        self,
        variables: dict[str, "Any"],
        settings: "DeckSettings",
        deck: "Deck",
        build_presentation: bool,
        build_handout: bool,
        build_print: bool,
    ):
        self._variables = variables
        self._settings = settings
        self._deck = deck
        self._build_presentation = build_presentation
        self._build_handout = build_handout
        self._build_print = build_print

    @abstractmethod
    def build(self) -> bool:
        raise NotImplementedError


class AssetsBuilder(GlobalComponent, key="assets_builder"):
    @abstractmethod
    def build(self) -> None:
        raise NotImplementedError


class Compiler(GlobalComponent, key="compiler"):
    @abstractmethod
    def compile(self, file: "Path") -> "CompileResult":
        raise NotImplementedError


def _load_components() -> None:
    from ..utils import import_module_and_submodules

    import_module_and_submodules(__name__)


_load_components()
