from pathlib import Path
from typing import TYPE_CHECKING, Any

from .protocols import (
    AssetsAnalyzerProtocol,
    AssetsBuilderProtocol,
    AssetsMetadataRetrieverProtocol,
    AssetsSearcherProtocol,
    CompilerProtocol,
    DeckBuilderProtocol,
    DeckFactoryProtocol,
    GlobalFactoryProtocol,
    MarkdownConverterProtocol,
    ParserProtocol,
    RendererProtocol,
)

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings, GlobalSettings
    from ..models import Deck, Lang


class GlobalSettingsFactory[T: "GlobalSettings"](GlobalFactoryProtocol):
    def __init__(self, settings: T) -> None:
        self._settings = settings

    def renderer(self) -> RendererProtocol:
        from .renderer import Renderer

        return Renderer(
            jinja_env_module=self._settings.paths.jinja2_env_module,
            global_factory=self,
        )

    def compiler(self) -> CompilerProtocol:
        if self._settings.compiler == "typst":
            from .typst_compiler import TypstCompiler

            return TypstCompiler(
                max_parallel=self._settings.typst_parallel_compilations
            )

        from .compiler import Compiler

        return Compiler(build_command=self._settings.build_command)

    def markdown_converter(self) -> MarkdownConverterProtocol:
        from .markdown_converter import PandocConverter

        # PandocConverter runs pandoc with a cwd matching the content
        # fragment's own (possibly deeply nested) position within the build
        # directory, so a bare relative path (e.g. in a --lua-filter=...
        # argument) couldn't resolve consistently: format it against the
        # resolved absolute paths instead, mirroring how GlobalPaths itself
        # resolves "{git_dir}/..."-style fields.
        paths = self._settings.paths
        pandoc_command = tuple(
            arg.format(git_dir=paths.git_dir, templates_dir=paths.templates_dir)
            for arg in self._settings.pandoc_command
        )
        return PandocConverter(pandoc_command=pandoc_command)

    def assets_builder(self) -> AssetsBuilderProtocol:
        from .assets_builder import AssetsBuilder

        return AssetsBuilder(
            assets_builders_module=self._settings.paths.assets_builders_module,
            assets_dir=self._settings.paths.assets_dir,
            compiler=self.compiler(),
        )

    def assets_metadata_retriever(self) -> AssetsMetadataRetrieverProtocol:
        from .assets_metadata_retriever import AssetsMetadataRetriever

        return AssetsMetadataRetriever(assets_dir=self._settings.paths.assets_dir)

    def assets_searcher(self) -> AssetsSearcherProtocol:
        from .assets_searcher import AssetsSearcher

        return AssetsSearcher(
            assets_dir=self._settings.paths.assets_dir,
            git_dir=self._settings.paths.git_dir,
            renderer=self.renderer(),
        )

    def assets_analyzer(self) -> AssetsAnalyzerProtocol:
        from .assets_analyzer import AssetsAnalyzer

        return AssetsAnalyzer(
            assets_dir=self._settings.paths.assets_dir,
            git_dir=self._settings.paths.git_dir,
            renderer=self.renderer(),
        )


class DeckSettingsFactory(GlobalSettingsFactory["DeckSettings"], DeckFactoryProtocol):
    def __init__(self, settings: "DeckSettings", *, lang: "Lang" = "fr") -> None:
        super().__init__(settings)
        self._lang = lang

    def parser(self) -> ParserProtocol:
        from .parser import Parser

        return Parser(
            local_latex_dir=self._settings.paths.local_latex_dir,
            shared_latex_dir=self._settings.paths.latex_dir,
            file_extensions=self._settings.file_extensions,
            lang=self._lang,
        )

    def deck_builder(
        self,
        variables: dict[str, Any],
        deck: "Deck",
        build_presentation: bool,
        build_handout: bool,
        build_print: bool,
        basedirs: tuple[Path, ...] | None = None,
    ) -> DeckBuilderProtocol:
        from .deck_builder import DeckBuilder

        output_dir = self._settings.paths.pdf_dir
        build_dir = self._settings.paths.build_dir
        if self._lang == "en":
            output_dir = output_dir / "en"
            build_dir = build_dir / "en"

        assets_dir = self._settings.paths.assets_dir
        dirs_to_link = (
            tuple(d for d in assets_dir.iterdir() if d.is_dir())
            if assets_dir.is_dir()
            else ()
        )

        return DeckBuilder(
            variables=variables,
            deck=deck,
            build_presentation=build_presentation,
            build_handout=build_handout,
            build_print=build_print,
            output_dir=output_dir,
            build_dir=build_dir,
            dirs_to_link=dirs_to_link,
            template=self._settings.paths.jinja2_main_template,
            basedirs=basedirs
            if basedirs is not None
            else (
                self._settings.paths.latex_dir,
                assets_dir,
                self._settings.paths.current_dir,
            ),
            renderer=self.renderer(),
            compiler=self.compiler(),
            markdown_converter=self.markdown_converter(),
        )
