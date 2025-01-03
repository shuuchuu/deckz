from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..configuring.registry import DeckComponent, GlobalComponent

if TYPE_CHECKING:
    from ..models import (
        AssetsMetadata,
        CompileResult,
        Deck,
        FlavorName,
        ResolvedPath,
        UnresolvedPath,
    )


class Parser(DeckComponent, key="parser"):
    """Build a deck from a definition.

    The definition can be a complete deck definition obtained from a yaml file or a \
    simpler one obtained from a single section or file.
    """

    @abstractmethod
    def from_deck_definition(self, deck_definition_path: Path) -> "Deck":
        """Parse a deck from a yaml definition.

        Args:
            deck_definition_path: Path to the yaml definition. It should be parsable \
                into a [`DeckDefinition`][deckz.models.DeckDefinition] by Pydantic.

        Returns:
            The parsed deck.
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
        variables: dict[str, Any],
        deck: "Deck",
        build_presentation: bool,
        build_handout: bool,
        build_print: bool,
    ):
        self._variables = variables
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
    def compile(self, file: Path) -> "CompileResult":
        raise NotImplementedError


class Renderer(GlobalComponent, key="renderer"):
    @abstractmethod
    def render_to_str(
        self, template_path: Path, /, **template_kwargs: Any
    ) -> tuple[str, "AssetsMetadata"]:
        raise NotImplementedError

    def render_to_path(
        self, template_path: Path, output_path: Path, /, **template_kwargs: Any
    ) -> "AssetsMetadata":
        from contextlib import suppress
        from filecmp import cmp
        from shutil import move
        from tempfile import NamedTemporaryFile

        try:
            with NamedTemporaryFile("w", encoding="utf8", delete=False) as fh:
                rendered, assets_metadata = self.render_to_str(
                    template_path, **template_kwargs
                )
                fh.write(rendered)
                fh.write("\n")
            if not output_path.exists() or not cmp(fh.name, str(output_path)):
                move(fh.name, output_path)
        finally:
            with suppress(FileNotFoundError):
                Path(fh.name).unlink()
        return assets_metadata


class AssetsMetadataRetriever(GlobalComponent, key="assets_metadata_retriever"):
    @property
    @abstractmethod
    def assets_metadata(self) -> "AssetsMetadata":
        raise NotImplementedError

    @abstractmethod
    def __call__(self, value: str) -> dict[str, Any] | None:
        raise NotImplementedError


class AssetsSearcher(GlobalComponent, key="assets_searcher"):
    @abstractmethod
    def search(self, asset: str) -> set["ResolvedPath"]:
        raise NotImplementedError


class AssetsAnalyzer(GlobalComponent, key="assets_analyzer"):
    @abstractmethod
    def sections_unlicensed_images(self) -> dict["UnresolvedPath", frozenset[Path]]:
        raise NotImplementedError


def _load_components() -> None:
    from ..utils import import_module_and_submodules

    import_module_and_submodules(__name__)


_load_components()
