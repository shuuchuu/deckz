from collections.abc import MutableSequence, MutableSet, Sequence, Set
from dataclasses import dataclass
from enum import Enum
from logging import getLogger
from multiprocessing import Pool, cpu_count
from pathlib import Path
from shutil import copyfile
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from ..building.compiling import CompileResult
from ..building.compiling import compile as compiling_compile
from ..building.rendering import Renderer
from ..exceptions import DeckzError
from ..models.deck import Deck, File, Part, Section
from ..models.scalars import PartName, ResolvedPath
from ..models.slides import PartSlides, Title, TitleOrContent
from ..processing import NodeVisitor
from ..utils import copy_file_if_newer
from . import Builder, BuilderConfig

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings


class CompileType(Enum):
    Handout = "handout"
    Presentation = "presentation"
    PrintHandout = "print-handout"


@dataclass(frozen=True)
class CompileItem:
    parts: Sequence[PartSlides]
    dependencies: Set[Path]
    compile_type: CompileType
    toc: bool


class DefaultBuilder(Builder):
    def __init__(
        self,
        variables: dict[str, Any],
        settings: "DeckSettings",
        deck: Deck,
        build_presentation: bool,
        build_handout: bool,
        build_print: bool,
    ):
        self._variables = variables
        self._settings = settings
        self._deck_name = deck.name
        self._parts_slides = _SlidesNodeVisitor(
            settings.paths.shared_dir, settings.paths.current_dir
        ).process(deck)
        self._dependencies = _PartDependenciesNodeVisitor().process(deck)
        self._presentation = build_presentation
        self._handout = build_handout
        self._print = build_print
        self._logger = getLogger(__name__)
        self._renderer = Renderer(settings)

    def _name_compile_item(
        self, compile_type: CompileType, name: PartName | None = None
    ) -> str:
        return (
            f"{self._deck_name}-{name}-{compile_type.value}"
            if name
            else f"{self._deck_name}-{compile_type.value}"
        ).lower()

    def build(self) -> bool:
        items = self._list_items()
        self._logger.info(f"Building {len(items)} PDFs.")
        with Pool(min(cpu_count(), len(items))) as pool:
            results = pool.starmap(self._build_item, items.items())
        for item_name, result in zip(items, results, strict=True):
            if not result.ok:
                self._logger.warning("Compilation %s errored", item_name)
                self._logger.warning("Captured %s stderr\n%s", item_name, result.stderr)
                self._logger.warning("Captured %s stdout\n%s", item_name, result.stdout)
        return all(result.ok for result in results)

    def _list_items(self) -> dict[str, CompileItem]:
        to_compile = {}
        all_slides = list(self._parts_slides.values())
        all_dependencies = frozenset().union(*self._dependencies.values())
        if self._handout:
            to_compile[self._name_compile_item(CompileType.Handout)] = CompileItem(
                all_slides, all_dependencies, CompileType.Handout, True
            )
        if self._print:
            to_compile[self._name_compile_item(CompileType.PrintHandout)] = CompileItem(
                all_slides, all_dependencies, CompileType.Handout, True
            )
        for name, slides in self._parts_slides.items():
            dependencies = self._dependencies[name]
            if self._presentation:
                to_compile[self._name_compile_item(CompileType.Presentation, name)] = (
                    CompileItem([slides], dependencies, CompileType.Presentation, False)
                )
            if self._handout:
                to_compile[self._name_compile_item(CompileType.Handout, name)] = (
                    CompileItem([slides], dependencies, CompileType.Handout, False)
                )
        return to_compile

    def _build_item(self, name: str, item: CompileItem) -> CompileResult:
        build_dir = self._setup_build_dir(name)
        latex_path = build_dir / f"{name}.tex"
        build_pdf_path = latex_path.with_suffix(".pdf")
        output_pdf_path = self._settings.paths.pdf_dir / f"{name}.pdf"
        self._render_latex(item, latex_path)
        copied = self._copy_dependencies(item.dependencies, build_dir)
        self._render_dependencies(copied)
        result = compiling_compile(latex_path, self._settings.build_command)
        if result.ok:
            self._settings.paths.pdf_dir.mkdir(parents=True, exist_ok=True)
            copyfile(build_pdf_path, output_pdf_path)
        return result

    def _setup_build_dir(self, name: str) -> Path:
        target_build_dir = self._settings.paths.build_dir / name
        target_build_dir.mkdir(parents=True, exist_ok=True)
        for item in [
            self._settings.paths.shared_img_dir,
            self._settings.paths.shared_tikz_pdf_dir,
            self._settings.paths.shared_plt_pdf_dir,
            self._settings.paths.shared_code_dir,
        ]:
            self._setup_link(target_build_dir / item.name, item)
        return target_build_dir

    def _render_latex(self, item: CompileItem, output_path: Path) -> None:
        self._renderer.render(
            template_path=self._settings.paths.jinja2_main_template,
            output_path=output_path,
            variables=self._variables,
            parts=item.parts,
            handout=item.compile_type
            in [CompileType.Handout, CompileType.PrintHandout],
            toc=item.toc,
            print=item.compile_type is CompileType.PrintHandout,
        )

    def _copy_dependencies(
        self, dependencies: Set[Path], target_build_dir: Path
    ) -> list[Path]:
        copied = []
        for dependency in dependencies:
            try:
                link_dir = (
                    target_build_dir
                    / dependency.relative_to(self._settings.paths.shared_dir).parent
                )
            except ValueError:
                link_dir = (
                    target_build_dir
                    / dependency.relative_to(self._settings.paths.current_dir).parent
                )
            link_dir.mkdir(parents=True, exist_ok=True)
            destination = (link_dir / dependency.name).with_suffix(".tex.j2")
            if (
                not destination.exists()
                or destination.stat().st_mtime < dependency.stat().st_mtime
            ):
                copy_file_if_newer(dependency, destination)
                copied.append(destination)
        return copied

    def _render_dependencies(self, to_render: list[Path]) -> None:
        for item in to_render:
            self._renderer.render(template_path=item, output_path=item.with_suffix(""))

    def _setup_link(self, source: Path, target: Path) -> None:
        if not target.exists():
            msg = (
                f"{target} could not be found. Please make sure it exists before "
                "proceeding"
            )
            raise DeckzError(msg)
        target = target.resolve()
        if source.is_symlink():
            if source.resolve().samefile(target):
                return
            msg = (
                f"{source} already exists in the build directory and does not point to "
                f"{target}. Please clean the build directory"
            )
            raise DeckzError(msg)
        if source.exists():
            msg = (
                f"{source} already exists in the build directory. Please clean the "
                "build directory"
            )
            raise DeckzError(msg)
        source.parent.mkdir(parents=True, exist_ok=True)
        source.symlink_to(target)


class DefaultParserConfig(BuilderConfig, component=DefaultBuilder):
    file_extension: str = ".tex"

    config_key: ClassVar[Literal["default_builder"]] = "default_builder"


class _SlidesNodeVisitor(NodeVisitor[[MutableSequence[TitleOrContent], int], None]):
    def __init__(self, shared_dir: Path, current_dir: Path) -> None:
        self._shared_dir = shared_dir
        self._current_dir = current_dir

    def process(self, deck: Deck) -> dict[PartName, PartSlides]:
        return {
            part_name: self._process_part(part)
            for part_name, part in deck.parts.items()
        }

    def _process_part(self, part: Part) -> PartSlides:
        sections: list[TitleOrContent] = []
        for node in part.nodes:
            node.accept(self, sections, 0)
        return PartSlides(part.title, sections)

    def visit_file(
        self, file: File, sections: MutableSequence[TitleOrContent], level: int
    ) -> None:
        if file.title:
            sections.append(Title(file.title, level))
        if file.resolved_path.is_relative_to(self._shared_dir):
            path = file.resolved_path.relative_to(self._shared_dir)
        elif file.resolved_path.is_relative_to(self._current_dir):
            path = file.resolved_path.relative_to(self._current_dir)
        else:
            raise ValueError
        path = path.with_suffix("")
        sections.append(str(path))

    def visit_section(
        self, section: Section, sections: MutableSequence[TitleOrContent], level: int
    ) -> None:
        if section.title:
            sections.append(Title(section.title, level))
        for node in section.nodes:
            node.accept(self, sections, level + 1)


class _PartDependenciesNodeVisitor(NodeVisitor[[MutableSet[ResolvedPath]], None]):
    def process(self, deck: Deck) -> dict[PartName, set[ResolvedPath]]:
        return {
            part_name: self._process_part(part)
            for part_name, part in deck.parts.items()
        }

    def _process_part(self, part: Part) -> set[ResolvedPath]:
        dependencies: set[ResolvedPath] = set()
        for node in part.nodes:
            node.accept(self, dependencies)
        return dependencies

    def visit_file(self, file: File, dependencies: MutableSet[ResolvedPath]) -> None:
        dependencies.add(file.resolved_path)

    def visit_section(
        self, section: Section, dependencies: MutableSet[ResolvedPath]
    ) -> None:
        for node in section.nodes:
            node.accept(self, dependencies)
