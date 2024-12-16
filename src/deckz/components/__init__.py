from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict

from ..configuring.registry import Config, configurable

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from ..configuring.settings import DeckSettings
    from ..models.deck import Deck
    from ..models.scalars import FlavorName


class Parser(ABC):
    """Build a deck from a definition.

    The definition can be a complete deck definition obtained from a yaml file or a \
    simpler one obtained from a single section or file.
    """

    @abstractmethod
    def __init__(
        self, local_latex_dir: "Path", shared_latex_dir: "Path", config: "ParserConfig"
    ) -> None:
        raise NotImplementedError

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


@configurable
class ParserConfig(BaseModel, Config[Parser]):
    model_config = ConfigDict(defer_build=True)
    config_key: ClassVar[str]


class Builder(ABC):
    @abstractmethod
    def __init__(
        self,
        variables: dict[str, "Any"],
        settings: "DeckSettings",
        deck: "Deck",
        build_presentation: bool,
        build_handout: bool,
        build_print: bool,
    ):
        raise NotImplementedError

    @abstractmethod
    def build(self) -> bool:
        raise NotImplementedError


@configurable
class BuilderConfig(BaseModel, Config[Builder]):
    model_config = ConfigDict(defer_build=True)
    config_key: ClassVar[str]


def _load_components() -> None:
    from ..utils import import_module_and_submodules

    import_module_and_submodules(__name__)


_load_components()
