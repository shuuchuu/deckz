from collections.abc import (
    Iterable,
    Mapping,
    MutableSequence,
    MutableSet,
    Sequence,
    Set,
)
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from json import dumps
from logging import getLogger
from multiprocessing import cpu_count
from pathlib import Path, PurePosixPath
from shutil import copyfile
from typing import Any

from rich.progress import BarColumn, Progress

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
from .protocols import (
    CompilerProtocol,
    DeckBuilderProtocol,
    MarkdownConverterProtocol,
    RendererProtocol,
)


class CompileType(Enum):
    Handout = "handout"
    Presentation = "presentation"
    PrintHandout = "print-handout"


def variables_fingerprint(variables: Mapping[str, Any]) -> str:
    """A short, stable hash of `variables`'s content.

    Used to disambiguate the same physical file included more than once in \
    the same build with different effective variables (e.g. two flavors of \
    the same section merged into one deck): each distinct fingerprint gets \
    its own rendered copy instead of colliding on one shared build artifact.

    Returns:
        A 16-character hex digest of `variables`'s content.
    """
    return sha256(
        dumps(variables, sort_keys=True, default=str).encode("utf8")
    ).hexdigest()[:16]


def dependency_relative_path(
    resolved_path: Path, basedirs: Iterable[Path], fingerprint: str
) -> PurePosixPath:
    r"""The extensionless path used both to `\input` a fragment and to name it.

    Relative to whichever of `basedirs` contains `resolved_path`, with \
    `fingerprint` appended to the stem -- the single place this naming \
    scheme is decided, so the main template's content reference (built by \
    `_SlidesNodeVisitor`) \
    and the on-disk rendered copy (built by \
    [`copy_dependencies`][deckz.components.deck_builder.copy_dependencies]) \
    always agree.

    Returns:
        `resolved_path`, relative to its `basedirs` entry, without its \
        suffix, with `fingerprint` appended to the stem.

    Raises:
        ValueError: If `resolved_path` isn't relative to any of `basedirs`.
    """
    for basedir in basedirs:
        if resolved_path.is_relative_to(basedir):
            relative_path = resolved_path.relative_to(basedir)
            break
    else:
        msg = f"could not find file {resolved_path}"
        raise ValueError(msg)
    stem_path = relative_path.with_suffix("")
    return PurePosixPath(stem_path.parent / f"{stem_path.name}-{fingerprint}")


@dataclass(frozen=True)
class DependencyRef:
    """A file to render into a build dir, identified by content, not just path.

    Two occurrences of the same `resolved_path` with different effective \
    `variables` (see [`File.variables`][deckz.models.File.variables]) are \
    two distinct `DependencyRef`s: `variables` is excluded from equality/hash \
    (dicts aren't hashable, and it's a pure function of `variables_fingerprint` \
    anyway), so a `set[DependencyRef]` naturally dedupes same-path-same-variables \
    occurrences while keeping same-path-different-variables ones apart.
    """

    resolved_path: ResolvedPath
    variables_fingerprint: str
    variables: dict[str, Any] = field(compare=False)


@dataclass(frozen=True)
class CompileItem:
    parts: Sequence[PartSlides]
    dependencies: Set[DependencyRef]
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
        markdown_converter: MarkdownConverterProtocol,
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
        self._markdown_converter = markdown_converter
        self._logger = getLogger(__name__)

    def build_deck(self) -> bool:
        items = self._list_items()
        self._markdown_fingerprint = self._markdown_converter.fingerprint()
        results = []
        with (
            Progress(
                "[progress.description]{task.description}",
                BarColumn(),
                "[progress.percentage]{task.percentage:>3.0f}%",
            ) as progress,
            # Threads, not processes: rendering is cheap next to pandoc and
            # the compiler, which both run in subprocesses. Staying in this
            # process is also what lets TypstCompiler keep its warm worker
            # processes from one `--watch` rebuild to the next.
            ThreadPoolExecutor(min(cpu_count(), len(items))) as pool,
        ):
            task_id = progress.add_task("Compiling…", total=len(items))
            for item_name, result in zip(
                items,
                pool.map(self._build_item_pair, items.items()),
                strict=True,
            ):
                results.append((item_name, result))
                progress.update(task_id, advance=1)
        for item_name, result in results:
            if not result.ok:
                self._logger.warning("Compilation %s errored", item_name)
                self._logger.warning("Captured %s stderr\n%s", item_name, result.stderr)
                self._logger.warning("Captured %s stdout\n%s", item_name, result.stdout)
        return all(result.ok for _, result in results)

    def _build_item_pair(self, pair: tuple[str, CompileItem]) -> CompileResult:
        return self._build_item(*pair)

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
                all_slides, all_dependencies, CompileType.PrintHandout, True
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
        build_dir = setup_build_dir(self._build_dir, name, self._dirs_to_link)
        main_path = build_dir / f"{name}{self._template.suffix}"
        build_pdf_path = main_path.with_suffix(".pdf")
        output_pdf_path = self._output_dir / f"{name}.pdf"
        self._render_main(item, main_path)
        # `copy_dependencies` only re-copies (and so re-renders/re-converts) a
        # fragment whose source is newer than its build copy, but a pandoc
        # command or filter change doesn't touch any source: force a full
        # pass whenever the converter's fingerprint moved since this item's
        # last successful render.
        fingerprint_path = build_dir / ".markdown-fingerprint"
        markdown_stale = (
            not fingerprint_path.is_file()
            or fingerprint_path.read_text(encoding="utf8") != self._markdown_fingerprint
        )
        copied = copy_dependencies(
            item.dependencies, build_dir, self._basedirs, force=markdown_stale
        )
        render_dependencies(
            self._renderer,
            self._markdown_converter,
            copied,
            target_suffix=self._template.suffix,
        )
        if markdown_stale:
            fingerprint_path.write_text(self._markdown_fingerprint, encoding="utf8")
        result = self._compiler.compile(main_path)
        if result.ok:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            copyfile(build_pdf_path, output_pdf_path)
        return result

    def _render_main(self, item: CompileItem, output_path: Path) -> None:
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


def setup_link(source: Path, target: Path) -> None:
    if not target.exists():
        msg = (
            f"{target} could not be found. Please make sure it exists before proceeding"
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


def setup_build_dir(build_dir: Path, name: str, dirs_to_link: Iterable[Path]) -> Path:
    target_build_dir = build_dir / name
    target_build_dir.mkdir(parents=True, exist_ok=True)
    for item in dirs_to_link:
        setup_link(target_build_dir / item.name, item)
    return target_build_dir


def copy_dependencies(
    dependencies: Iterable[DependencyRef],
    target_build_dir: Path,
    basedirs: Iterable[Path],
    *,
    force: bool = False,
) -> list[tuple[Path, dict[str, Any]]]:
    copied = []
    for dependency in dependencies:
        relative_path = dependency_relative_path(
            dependency.resolved_path, basedirs, dependency.variables_fingerprint
        )
        build_path = (target_build_dir / relative_path).with_name(
            f"{relative_path.name}{dependency.resolved_path.suffix}.j2"
        )
        if force:
            build_path.parent.mkdir(parents=True, exist_ok=True)
            copyfile(dependency.resolved_path, build_path)
            copied.append((build_path, dependency.variables))
        elif copy_file_if_newer(dependency.resolved_path, build_path):
            copied.append((build_path, dependency.variables))
    return copied


def render_dependencies(
    renderer: RendererProtocol,
    markdown_converter: MarkdownConverterProtocol,
    to_render: Iterable[tuple[Path, dict[str, Any]]],
    *,
    target_suffix: str = ".tex",
) -> None:
    for item_path, variables in to_render:
        rendered_path = item_path.with_suffix("")
        renderer.render_to_path(item_path, rendered_path, variables=variables)
        if rendered_path.suffix == ".md":
            markdown_converter.convert(
                rendered_path, rendered_path.with_suffix(target_suffix)
            )


class PartDependenciesNodeVisitor(NodeVisitor[[MutableSet[DependencyRef]], None]):
    def process(self, deck: Deck) -> dict[PartName, set[DependencyRef]]:
        return {
            part_name: self._process_part(part)
            for part_name, part in deck.parts.items()
        }

    def _process_part(self, part: Part) -> set[DependencyRef]:
        dependencies: set[DependencyRef] = set()
        for node in part.nodes:
            node.accept(self, dependencies)
        return dependencies

    def visit_file(self, file: File, dependencies: MutableSet[DependencyRef]) -> None:
        dependencies.add(
            DependencyRef(
                file.resolved_path,
                variables_fingerprint(file.variables),
                file.variables,
            )
        )

    def visit_section(
        self, section: Section, dependencies: MutableSet[DependencyRef]
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
        fingerprint = variables_fingerprint(file.variables)
        reference = dependency_relative_path(
            file.resolved_path, self._basedirs, fingerprint
        )
        sections.append(str(reference))

    def visit_section(
        self, section: Section, sections: MutableSequence[TitleOrContent], level: int
    ) -> None:
        if section.title:
            sections.append(Title(section.title, level))
            level += 1
        for node in section.nodes:
            node.accept(self, sections, level)
