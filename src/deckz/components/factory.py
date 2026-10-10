from pathlib import Path
from typing import TYPE_CHECKING, Any

from .protocols import (
    AssetsAnalyzerProtocol,
    AssetsBuilderProtocol,
    AssetsMetadataRetrieverProtocol,
    AssetsSearcherProtocol,
    ChecksRunnerProtocol,
    CompilerProtocol,
    DeckBuilderProtocol,
    DeckFactoryProtocol,
    GlobalFactoryProtocol,
    MarkdownConverterProtocol,
    ParserProtocol,
    ProgressReporterProtocol,
    RendererProtocol,
)

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings, GlobalSettings
    from ..models import Lang, ResolvedDeck
    from .deck_builder import OutputFormat


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
        from .compiler import TypstCompiler
        from .machine_slots import MachineSlots

        # Relative to the git root, whatever deckz's own working directory.
        paths = self._settings.paths
        return TypstCompiler(
            max_parallel=self._settings.typst_parallel_compilations,
            font_paths=tuple(
                paths.git_dir
                / path.format(
                    git_dir=paths.git_dir,
                    assets_dir=paths.assets_dir,
                    templates_dir=paths.templates_dir,
                )
                for path in self._settings.typst_font_paths
            ),
            ignore_system_fonts=self._settings.typst_ignore_system_fonts,
            memory_max=self._settings.typst_memory_max,
            machine_slots=(
                None
                if self._settings.typst_machine_compilations is None
                else MachineSlots(self._settings.typst_machine_compilations)
            ),
        )

    def markdown_converter(self) -> MarkdownConverterProtocol:
        return self._pandoc_converter(self._settings.pandoc_command)

    def html_markdown_converter(self) -> MarkdownConverterProtocol:
        return self._pandoc_converter(self._settings.html_pandoc_command)

    def html_packager(self) -> CompilerProtocol:
        from .html_packager import HtmlPackager

        return HtmlPackager(static_dirs=self._settings.html_static_dirs)

    def _pandoc_converter(self, command: tuple[str, ...]) -> MarkdownConverterProtocol:
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
            for arg in command
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

    def checks_runner(self) -> ChecksRunnerProtocol:
        from .checks import ChecksRunner

        return ChecksRunner(
            settings=self._settings, checks_module=self._settings.paths.checks_module
        )

    def shared_parser(
        self, lang: "Lang" = "fr", *, lenient: bool = False
    ) -> ParserProtocol:
        """Parser resolving everything against the shared content only.

        Used for decks that don't belong to any deck directory, e.g. a single \
        shared section's flavor or every shared section at once.

        Args:
            lang: Language to parse in.
            lenient: Let a translation map missing `lang` fall back instead \
                of failing (see [`Parser`][deckz.components.parser.Parser]).

        Returns:
            The parser.
        """
        from .parser import Parser

        content_dir = self._settings.paths.content_dir
        return Parser(
            local_content_dir=content_dir,
            shared_content_dir=content_dir,
            file_extensions=self._settings.file_extensions,
            lang=lang,
            lenient=lenient,
        )


class DeckSettingsFactory(GlobalSettingsFactory["DeckSettings"], DeckFactoryProtocol):
    def __init__(
        self, settings: "DeckSettings", *, lang: "Lang" = "fr", lenient: bool = False
    ) -> None:
        super().__init__(settings)
        self._lang = lang
        self._lenient = lenient

    def parser(self) -> ParserProtocol:
        from .parser import Parser

        return Parser(
            local_content_dir=self._settings.paths.local_content_dir,
            shared_content_dir=self._settings.paths.content_dir,
            file_extensions=self._settings.file_extensions,
            lang=self._lang,
            lenient=self._lenient,
        )

    def deck_builder(
        self,
        variables: dict[str, Any],
        deck: "ResolvedDeck",
        build_presentation: bool,
        build_handout: bool,
        build_print: bool,
        build_html: bool = False,
        build_part_handouts: bool = True,
        basedirs: tuple[Path, ...] | None = None,
        progress: ProgressReporterProtocol | None = None,
    ) -> DeckBuilderProtocol:
        from ..models import lang_dir
        from .deck_builder import DeckBuilder, Format, OutputFormat
        from .frame_markers import FrameMarkingConverter
        from .progress import NullProgress

        paths = self._settings.paths
        pdf_dir, html_dir, build_dir = (
            lang_dir(paths.pdf_dir, self._lang),
            lang_dir(paths.html_dir, self._lang),
            lang_dir(paths.build_dir, self._lang),
        )

        assets_dir = paths.assets_dir
        dirs_to_link = (
            tuple(d for d in assets_dir.iterdir() if d.is_dir())
            if assets_dir.is_dir()
            else ()
        )

        formats = {
            Format.Typst: OutputFormat(
                template=paths.jinja2_main_template,
                fragment_suffix=".typ",
                # `deckz show frames` reads the markers it adds.
                markdown_converter=FrameMarkingConverter(self.markdown_converter()),
                compiler=self.compiler(),
                output_dir=pdf_dir,
                artifact_suffix=".pdf",
                output_suffix=".pdf",
            )
        }
        if build_html:
            formats[Format.Html] = self._html_format(html_dir)

        return DeckBuilder(
            variables=variables,
            deck=deck,
            build_presentation=build_presentation,
            build_handout=build_handout,
            build_print=build_print,
            build_html=build_html,
            build_part_handouts=build_part_handouts,
            formats=formats,
            build_dir=build_dir,
            dirs_to_link=dirs_to_link,
            basedirs=basedirs
            if basedirs is not None
            else (paths.content_dir, assets_dir, paths.current_dir),
            renderer=self.renderer(),
            progress=progress if progress is not None else NullProgress(),
        )

    def _html_format(self, html_dir: Path) -> "OutputFormat":
        from ..exceptions import InvalidConfigurationError
        from .deck_builder import OutputFormat

        template = self._settings.paths.jinja2_html_main_template
        if not self._settings.html_pandoc_command:
            msg = "HTML output needs an `html_pandoc_command` in deckz.yml"
            raise InvalidConfigurationError(msg)
        if not template.is_file():
            msg = f"HTML output needs a main template, {template} not found"
            raise InvalidConfigurationError(msg)
        return OutputFormat(
            template=template,
            fragment_suffix=".html",
            markdown_converter=self.html_markdown_converter(),
            compiler=self.html_packager(),
            output_dir=html_dir,
            artifact_suffix=".site",
            output_suffix="",
        )
