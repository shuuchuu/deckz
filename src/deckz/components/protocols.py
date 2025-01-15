from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ..models import (
        AssetsMetadata,
        CompileResult,
        Deck,
        FlavorName,
        ResolvedPath,
        UnresolvedPath,
    )


class ParserProtocol(Protocol):
    """Build a deck from a definition.

    The definition can be a complete deck definition obtained from a yaml file or a \
    simpler one obtained from a single section or file.
    """

    def from_deck_definition(self, deck_definition_path: Path) -> "Deck":
        """Parse a deck from a yaml definition.

        Args:
            deck_definition_path: Path to the yaml definition. It should be parsable \
                into a [`DeckDefinition`][deckz.models.DeckDefinition] by Pydantic.

        Returns:
            The parsed deck.
        """

    def from_section(self, section: str, flavor: "FlavorName") -> "Deck": ...

    def from_file(self, latex: str) -> "Deck": ...


class DeckBuilderProtocol(Protocol):
    def build_deck(self) -> bool: ...


class AssetsBuilderProtocol(Protocol):
    def build_assets(self) -> None: ...


class CompilerProtocol(Protocol):
    def compile(self, file: Path) -> "CompileResult": ...


class RendererProtocol(Protocol):
    def render_to_str(
        self, template_path: Path, /, **template_kwargs: Any
    ) -> tuple[str, "AssetsMetadata"]: ...

    def render_to_path(
        self, template_path: Path, output_path: Path, /, **template_kwargs: Any
    ) -> "AssetsMetadata": ...


class AssetsMetadataRetrieverProtocol(Protocol):
    @property
    def assets_metadata(self) -> "AssetsMetadata": ...

    def __call__(self, value: str) -> dict[str, Any] | None: ...


class AssetsSearcherProtocol(Protocol):
    def search(self, asset: str) -> set["ResolvedPath"]: ...


class AssetsAnalyzerProtocol(Protocol):
    def sections_unlicensed_images(self) -> dict["UnresolvedPath", frozenset[Path]]: ...


class GlobalFactoryProtocol(Protocol):
    def renderer(self) -> RendererProtocol: ...

    def compiler(self) -> CompilerProtocol: ...

    def assets_builder(self) -> AssetsBuilderProtocol: ...

    def assets_metadata_retriever(self) -> AssetsMetadataRetrieverProtocol: ...

    def assets_searcher(self) -> AssetsSearcherProtocol: ...

    def assets_analyzer(self) -> AssetsAnalyzerProtocol: ...


class DeckFactoryProtocol(GlobalFactoryProtocol, Protocol):
    def deck_builder(
        self,
        variables: dict[str, Any],
        deck: "Deck",
        build_presentation: bool,
        build_handout: bool,
        build_print: bool,
    ) -> DeckBuilderProtocol: ...

    def parser(self) -> ParserProtocol: ...
