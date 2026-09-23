from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from jinja2 import Environment

    from ..models import (
        AssetsMetadata,
        CompileResult,
        Deck,
        FlavorName,
        ResolvedPath,
        Section,
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

    def all_files_section(self, section: str) -> "Section":
        """Build a section from every file physically present in its directory.

        Unlike \
        [`from_section`][deckz.components.protocols.ParserProtocol.from_section], \
        this ignores named flavors entirely: the section is expanded to every \
        file in its own directory, resolved through the same local-before-shared \
        lookup as any other file.

        Args:
            section: Shared/latex-relative section id, e.g. "python/basics".

        Returns:
            The built section.
        """


class DeckBuilderProtocol(Protocol):
    def build_deck(self) -> bool: ...


class AssetsBuilderProtocol(Protocol):
    def build_assets(self) -> None: ...

    def watched_dirs(self) -> Iterable[Path]:
        """Directories whose changes should trigger a rebuild (`deckz watch assets`)."""


class CompilerProtocol(Protocol):
    def compile(self, file: Path) -> "CompileResult": ...


class MarkdownConverterProtocol(Protocol):
    """Convert a rendered Markdown file to LaTeX (or another output format).

    Implementations shell out to `pandoc`; the actual command (binary, \
    `--slide-level`, `--lua-filter=...`, etc.) is entirely configured by the \
    target repo via `deckz.yml`'s `pandoc_command`.
    """

    def convert(self, source: Path, destination: Path) -> None: ...

    def fingerprint(self) -> str:
        """A stable fingerprint of this converter's configuration.

        Used by the deck builder to invalidate cached fragments \
        when the pandoc command or a referenced filter file changes, even \
        though the Markdown source itself didn't.
        """


class RendererProtocol(Protocol):
    def render_to_str(
        self, template_path: Path, /, **template_kwargs: Any
    ) -> tuple[str, "AssetsMetadata"]: ...

    def render_to_path(
        self, template_path: Path, output_path: Path, /, **template_kwargs: Any
    ) -> "AssetsMetadata": ...

    def environment_for(self, suffix: str) -> "Environment": ...


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

    def markdown_converter(self) -> MarkdownConverterProtocol: ...

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
        basedirs: tuple[Path, ...] | None = None,
    ) -> DeckBuilderProtocol: ...

    def parser(self) -> ParserProtocol: ...
