from collections.abc import Iterable, MutableSequence, MutableSet, Sequence, Set
from dataclasses import dataclass
from enum import Enum
from logging import getLogger
from multiprocessing import Pool, cpu_count
from pathlib import Path, PurePosixPath
from shutil import copyfile
from typing import Any

from ..exceptions import DeckzError
from ..models import (
    Deck,
    File,
    NodeVisitor,
    Part,
    PartName,
    PartSlides,
    ResolvedPath,
    Section,
    Title,
    TitleOrContent,
)
from ..utils import copy_file_if_newer
from .compiler import CompileResult
from .protocols import CompilerProtocol, DeckBuilderProtocol, RendererProtocol


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


class DeckBuilder(DeckBuilderProtocol):
    def __init__(
        self,
        variables: dict[str, Any],
        deck: Deck,
        build_presentation: bool,
        build_handout: bool,
        build_print: bool,
        output_dir: Path,
        build_dir: Path,
        dirs_to_link: tuple[Path, ...],
        template: Path,
        basedirs: tuple[Path, ...],
        compiler: CompilerProtocol,
        renderer: RendererProtocol,
    ):
        self._variables = variables
        self._build_presentation = build_presentation
        self._build_handout = build_handout
        self._build_print = build_print
        self._deck_name = deck.name
        self._parts_slides = _SlidesNodeVisitor(basedirs).process(deck)
        self._dependencies = PartDependenciesNodeVisitor().process(deck)
        self._output_dir = output_dir
        self._build_dir = build_dir
        self._dirs_to_link = dirs_to_link
        self._template = template
        self._basedirs = basedirs
        self._compiler = compiler
        self._renderer = renderer
        self._logger = getLogger(__name__)

    def build_deck(self) -> bool:
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

    def _name_compile_item(
        self, compile_type: CompileType, name: PartName | None = None
    ) -> str:
        return (
            f"{self._deck_name}-{name}-{compile_type.value}"
            if name
            else f"{self._deck_name}-{compile_type.value}"
        ).lower()

    def _list_items(self) -> dict[str, CompileItem]:
        to_compile = {}
        all_slides = list(self._parts_slides.values())
        all_dependencies = frozenset().union(*self._dependencies.values())
        if self._build_handout:
            to_compile[self._name_compile_item(CompileType.Handout)] = CompileItem(
                all_slides, all_dependencies, CompileType.Handout, True
            )
        if self._build_print:
            to_compile[self._name_compile_item(CompileType.PrintHandout)] = CompileItem(
                all_slides, all_dependencies, CompileType.Handout, True
            )
        for name, slides in self._parts_slides.items():
            dependencies = self._dependencies[name]
            if self._build_presentation:
                to_compile[self._name_compile_item(CompileType.Presentation, name)] = (
                    CompileItem([slides], dependencies, CompileType.Presentation, False)
                )
            if self._build_handout:
                to_compile[self._name_compile_item(CompileType.Handout, name)] = (
                    CompileItem([slides], dependencies, CompileType.Handout, False)
                )
        return to_compile

    def _build_item(self, name: str, item: CompileItem) -> CompileResult:
        build_dir = self._setup_build_dir(name)
        latex_path = build_dir / f"{name}.tex"
        build_pdf_path = latex_path.with_suffix(".pdf")
        output_pdf_path = self._output_dir / f"{name}.pdf"
        self._render_latex(item, latex_path)
        copied = self._copy_dependencies(item.dependencies, build_dir)
        self._render_dependencies(copied)
        result = self._compiler.compile(latex_path)
        if result.ok:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            copyfile(build_pdf_path, output_pdf_path)
        return result

    def _setup_build_dir(self, name: str) -> Path:
        target_build_dir = self._build_dir / name
        target_build_dir.mkdir(parents=True, exist_ok=True)
        for item in self._dirs_to_link:
            self._setup_link(target_build_dir / item.name, item)
        return target_build_dir

    def _render_latex(self, item: CompileItem, output_path: Path) -> None:
        self._renderer.render_to_path(
            self._template,
            output_path,
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
            for basedir in self._basedirs:
                if dependency.is_relative_to(basedir):
                    relative_path = dependency.relative_to(basedir)
                    break
            else:
                raise ValueError
            build_path = (target_build_dir / relative_path).with_suffix(".tex.j2")
            if copy_file_if_newer(dependency, build_path):
                copied.append(build_path)
        return copied

    def _render_dependencies(self, to_render: list[Path]) -> None:
        for item in to_render:
            self._renderer.render_to_path(item, item.with_suffix(""))

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


class PartDependenciesNodeVisitor(NodeVisitor[[MutableSet[ResolvedPath]], None]):
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


class _SlidesNodeVisitor(NodeVisitor[[MutableSequence[TitleOrContent], int], None]):
    def __init__(self, basedirs: Iterable[Path]) -> None:
        self._basedirs = tuple(basedirs)

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
        for basedir in self._basedirs:
            if file.resolved_path.is_relative_to(basedir):
                path = file.resolved_path.relative_to(basedir)
                break
        else:
            msg = f"could not find file {file}"
            raise ValueError(msg)
        path = path.with_suffix("")
        sections.append(str(PurePosixPath(path)))

    def visit_section(
        self, section: Section, sections: MutableSequence[TitleOrContent], level: int
    ) -> None:
        if section.title:
            sections.append(Title(section.title, level))
        for node in section.nodes:
            node.accept(self, sections, level + 1)
