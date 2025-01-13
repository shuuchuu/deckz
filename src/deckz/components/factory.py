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
    ParserProtocol,
    RendererProtocol,
)

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings, GlobalSettings
    from ..models import Deck


class GlobalSettingsFactory[T: "GlobalSettings"](GlobalFactoryProtocol):
    def __init__(self, settings: T) -> None:
        self._settings = settings

    def renderer(self) -> RendererProtocol:
        from .renderer import Renderer

        return Renderer(
            default_img_values=self._settings.default_img_values,
            assets_dir=self._settings.paths.shared_dir,
            global_factory=self,
        )

    def compiler(self) -> CompilerProtocol:
        from .compiler import Compiler

        return Compiler(build_command=self._settings.build_command)

    def assets_builder(self) -> AssetsBuilderProtocol:
        from .assets_builder import (
            AssetsBuilder,
            PlotlyAssetsBuilder,
            PltAssetsBuilder,
            TikzAssetsBuilder,
        )

        return AssetsBuilder(
            assets_builders=(
                PltAssetsBuilder(output_dir=self._settings.paths.shared_plt_pdf_dir),
                PlotlyAssetsBuilder(
                    output_dir=self._settings.paths.shared_plotly_pdf_dir
                ),
                TikzAssetsBuilder(
                    input_dir=self._settings.paths.tikz_dir,
                    output_dir=self._settings.paths.shared_tikz_pdf_dir,
                    assets_dir=self._settings.paths.shared_dir,
                    compiler=self.compiler(),
                ),
            )
        )

    def assets_metadata_retriever(self) -> AssetsMetadataRetrieverProtocol:
        from .assets_metadata_retriever import AssetsMetadataRetriever

        return AssetsMetadataRetriever(assets_dir=self._settings.paths.shared_dir)

    def assets_searcher(self) -> AssetsSearcherProtocol:
        from .assets_searcher import AssetsSearcher

        return AssetsSearcher(
            assets_dir=self._settings.paths.shared_dir,
            git_dir=self._settings.paths.git_dir,
            renderer=self.renderer(),
        )

    def assets_analyzer(self) -> AssetsAnalyzerProtocol:
        from .assets_analyzer import AssetsAnalyzer

        return AssetsAnalyzer(
            assets_dir=self._settings.paths.shared_dir,
            git_dir=self._settings.paths.git_dir,
            renderer=self.renderer(),
        )


class DeckSettingsFactory(GlobalSettingsFactory["DeckSettings"], DeckFactoryProtocol):
    def __init__(self, settings: "DeckSettings") -> None:
        super().__init__(settings)

    def parser(self) -> ParserProtocol:
        from .parser import Parser

        return Parser(
            local_latex_dir=self._settings.paths.local_latex_dir,
            shared_latex_dir=self._settings.paths.shared_latex_dir,
            file_extension=self._settings.file_extension,
        )

    def deck_builder(
        self,
        variables: dict[str, Any],
        deck: "Deck",
        build_presentation: bool,
        build_handout: bool,
        build_print: bool,
    ) -> DeckBuilderProtocol:
        from .deck_builder import DeckBuilder

        return DeckBuilder(
            variables=variables,
            deck=deck,
            build_presentation=build_presentation,
            build_handout=build_handout,
            build_print=build_print,
            output_dir=self._settings.paths.pdf_dir,
            build_dir=self._settings.paths.build_dir,
            dirs_to_link=(
                self._settings.paths.shared_img_dir,
                self._settings.paths.shared_tikz_pdf_dir,
                self._settings.paths.shared_plt_pdf_dir,
                self._settings.paths.shared_plotly_pdf_dir,
                self._settings.paths.shared_code_dir,
            ),
            template=self._settings.paths.jinja2_main_template,
            basedirs=(
                self._settings.paths.shared_dir,
                self._settings.paths.current_dir,
            ),
            renderer=self.renderer(),
            compiler=self.compiler(),
        )
