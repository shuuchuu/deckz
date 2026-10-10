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
from time import perf_counter
from traceback import extract_tb
from typing import Any

from jinja2 import TemplateError, TemplateSyntaxError

from ..exceptions import DeckzError, RenderError
from ..models import (
    CompileResult,
    Deck,
    File,
    NodeVisitor,
    Part,
    PartName,
    PartSlides,
    ResolvedDeck,
    ResolvedPath,
    Section,
    Title,
    TitleOrContent,
)
from ..utils import copy_file_if_changed, file_changed, sync_tree
from .protocols import (
    CompilerProtocol,
    DeckBuilderProtocol,
    MarkdownConverterProtocol,
    ProgressReporterProtocol,
    RendererProtocol,
)

_logger = getLogger(__name__)


class Format(Enum):
    """What a compilation produces: a PDF through Typst, or an HTML directory."""

    Typst = "typst"
    Html = "html"


class CompileType(Enum):
    Handout = "handout"
    Presentation = "presentation"
    PrintHandout = "print-handout"
    Html = "html"

    @property
    def format(self) -> Format:
        return Format.Html if self is CompileType.Html else Format.Typst


@dataclass(frozen=True)
class OutputFormat:
    """How to build one [`Format`][deckz.components.deck_builder.Format].

    A compilation renders `template` to `<name><template suffix>` in its \
    build dir, next to its fragments converted by `markdown_converter` to \
    `fragment_suffix` files, then `compiler` turns it into an artifact next \
    to it, `<name><artifact_suffix>`: a file (the PDF) or a directory (the \
    packaged HTML), published to `output_dir` as `<name><output_suffix>`.
    """

    template: Path
    fragment_suffix: str
    markdown_converter: MarkdownConverterProtocol
    compiler: CompilerProtocol
    output_dir: Path
    artifact_suffix: str
    output_suffix: str

    def output_path(self, name: str) -> Path:
        return self.output_dir / f"{name}{self.output_suffix}"


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
    """The extensionless path used both to `#include` a fragment and to name it.

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
    variables: Mapping[str, Any] = field(compare=False)


@dataclass(frozen=True)
class PlannedCompile:
    """One PDF or HTML output a build would produce, and what it would render first."""

    name: str
    """Name of the compilation, e.g. `"abc-handout"`."""

    output_path: Path
    """Where the output would be written."""

    fragments: int
    """How many content fragments the output includes."""

    full_render: bool
    """Whether every fragment would be rendered: on a first build, or after a \
    change of the Markdown converter's command or filters."""

    changed_fragments: tuple[ResolvedPath, ...]
    """Fragments new or changed since this output's last build, rendered even \
    without `full_render`."""


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
        deck: ResolvedDeck,
        build_presentation: bool,
        build_handout: bool,
        build_print: bool,
        build_html: bool,
        formats: Mapping[Format, OutputFormat],
        build_dir: Path,
        dirs_to_link: tuple[Path, ...],
        basedirs: tuple[Path, ...],
        renderer: RendererProtocol,
        progress: ProgressReporterProtocol,
        build_part_handouts: bool = True,
    ):
        self._variables = variables
        self._build_presentation = build_presentation
        self._build_handout = build_handout
        self._build_print = build_print
        self._build_html = build_html
        self._build_part_handouts = build_part_handouts
        self._deck_name = deck.name
        self._parts_slides = _SlidesNodeVisitor(basedirs).process(deck)
        self._dependencies = PartDependenciesNodeVisitor().process(deck)
        self._formats = formats
        self._build_dir = build_dir
        self._dirs_to_link = dirs_to_link
        self._basedirs = basedirs
        self._renderer = renderer
        self._progress = progress
        self._logger = getLogger(__name__)
        missing = {
            item.compile_type.format for item in self._list_items().values()
        } - formats.keys()
        if missing:
            msg = f"no output format configured for {sorted(f.value for f in missing)}"
            raise ValueError(msg)

    def output_paths(self) -> list[Path]:
        """Where `build_deck` writes its outputs, PDFs and HTML directories.

        Returns:
            One path per output, in compilation order.
        """
        return [
            self._formats[item.compile_type.format].output_path(name)
            for name, item in self._list_items().items()
        ]

    def plan(self) -> list[PlannedCompile]:
        """What `build_deck` would compile and render, without doing any of it.

        Returns:
            One entry per PDF, in compilation order.
        """
        planned = []
        for name, item in self._list_items().items():
            output_format = self._formats[item.compile_type.format]
            build_dir = self._build_dir / name
            fingerprint_path = build_dir / ".markdown-fingerprint"
            full_render = (
                not fingerprint_path.is_file()
                or fingerprint_path.read_text(encoding="utf8")
                != output_format.markdown_converter.fingerprint()
            )
            changed = tuple(
                sorted(
                    dependency.resolved_path
                    for dependency in item.dependencies
                    if file_changed(
                        dependency.resolved_path,
                        build_copy_path(dependency, build_dir, self._basedirs),
                    )
                )
            )
            planned.append(
                PlannedCompile(
                    name=name,
                    output_path=output_format.output_path(name),
                    fragments=len(item.dependencies),
                    full_render=full_render,
                    changed_fragments=changed,
                )
            )
        return planned

    def build_deck(self) -> bool:
        items = self._list_items()
        if not items:
            self._logger.warning(
                "Nothing to compile: handout, presentation, print and html are all "
                "disabled"
            )
            return True
        self._markdown_fingerprints = {
            output_format: self._formats[output_format].markdown_converter.fingerprint()
            for output_format in {item.compile_type.format for item in items.values()}
        }
        results = []
        # Threads, not processes: rendering is cheap next to pandoc and the
        # compiler, which both run in subprocesses. Staying in this process
        # is also what lets TypstCompiler keep its warm worker processes from
        # one `--watch` rebuild to the next.
        pool = ThreadPoolExecutor(min(cpu_count(), len(items)))
        try:
            with self._progress.track("Compiling…", len(items)) as advance:
                for item_name, result in zip(
                    items,
                    pool.map(self._build_item_pair, items.items()),
                    strict=True,
                ):
                    results.append((item_name, result))
                    advance()
        except BaseException:
            # E.g. Ctrl-C: let it reach the CLI at once, which kills the
            # compiler's processes, rather than wait for the compilations
            # running; and don't start those still queued.
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        pool.shutdown()
        for item_name, result in results:
            if not result.ok:
                self._logger.warning("Compilation %s errored", item_name)
                self._logger.warning(
                    "Captured %s diagnostics\n%s", item_name, result.diagnostics
                )
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
        if self._build_html:
            to_compile[self._name_compile_item(CompileType.Html)] = CompileItem(
                all_slides, all_dependencies, CompileType.Html, True
            )
        for name, slides in self._parts_slides.items():
            dependencies = self._dependencies[name]
            if self._build_presentation:
                to_compile[self._name_compile_item(CompileType.Presentation, name)] = (
                    CompileItem([slides], dependencies, CompileType.Presentation, False)
                )
            if self._build_handout and self._build_part_handouts:
                to_compile[self._name_compile_item(CompileType.Handout, name)] = (
                    CompileItem([slides], dependencies, CompileType.Handout, False)
                )
        return to_compile

    def _build_item(self, name: str, item: CompileItem) -> CompileResult:
        start = perf_counter()
        output_format = self._formats[item.compile_type.format]
        markdown_fingerprint = self._markdown_fingerprints[item.compile_type.format]
        build_dir = setup_build_dir(self._build_dir, name, self._dirs_to_link)
        main_path = build_dir / f"{name}{output_format.template.suffix}"
        # `copy_dependencies` only re-copies (and so re-renders/re-converts) a
        # fragment whose source differs from its build copy, but a pandoc
        # command or filter change doesn't touch any source: force a full
        # pass whenever the converter's fingerprint moved since this item's
        # last successful render.
        fingerprint_path = build_dir / ".markdown-fingerprint"
        markdown_stale = (
            not fingerprint_path.is_file()
            or fingerprint_path.read_text(encoding="utf8") != markdown_fingerprint
        )
        if markdown_stale:
            self._logger.debug(
                "%s: rendering every fragment, first build or the Markdown "
                "converter changed",
                name,
            )
        copied = copy_dependencies(
            item.dependencies, build_dir, self._basedirs, force=markdown_stale
        )
        render_dependencies(
            self._renderer,
            output_format.markdown_converter,
            copied,
            output_format.fragment_suffix,
        )
        if markdown_stale:
            fingerprint_path.write_text(markdown_fingerprint, encoding="utf8")
        # After the fragments: a main template may inline them (`fragment`).
        self._render_main(item, output_format, main_path)
        rendered = perf_counter()
        result = output_format.compiler.compile(main_path)
        self._logger.debug(
            "%s: rendered %d of %d fragments in %.2fs, compiled in %.2fs",
            name,
            len(copied),
            len(item.dependencies),
            rendered - start,
            perf_counter() - rendered,
        )
        if result.ok:
            publish(
                main_path.with_suffix(output_format.artifact_suffix),
                output_format.output_path(name),
            )
        return result

    def _render_main(
        self, item: CompileItem, output_format: OutputFormat, output_path: Path
    ) -> None:
        build_dir = output_path.parent

        def fragment(section: str) -> str:
            path = build_dir / f"{section}{output_format.fragment_suffix}"
            return path.read_text(encoding="utf8")

        self._renderer.render_to_path(
            output_format.template,
            output_path,
            variables=self._variables,
            parts=item.parts,
            handout=item.compile_type
            in [CompileType.Handout, CompileType.PrintHandout],
            toc=item.toc,
            print=item.compile_type is CompileType.PrintHandout,
            fragment=fragment,
        )


def publish(artifact: Path, output: Path) -> None:
    """Copy a compilation's artifact, a file or a directory, to `output`.

    A directory is synced: only changed files are copied, and files no \
    longer in `artifact` are removed from `output`.
    """
    if not artifact.is_dir():
        output.parent.mkdir(parents=True, exist_ok=True)
        copyfile(artifact, output)
        return
    sync_tree(
        {
            PurePosixPath(path.relative_to(artifact).as_posix()): path
            for path in artifact.rglob("*")
            if path.is_file()
        },
        output,
    )


def setup_link(source: Path, target: Path) -> None:
    if not target.exists():
        msg = (
            f"{target} could not be found. Please make sure it exists before proceeding"
        )
        raise DeckzError(msg)
    target = target.resolve()
    if source.is_symlink():
        if source.exists() and source.resolve().samefile(target):
            return
        # A link deckz made itself, left pointing elsewhere or nowhere, e.g.
        # by a rename of the directories it links to: relinking loses nothing.
        source.unlink()
    elif source.exists():
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


def build_copy_path(
    dependency: DependencyRef, target_build_dir: Path, basedirs: Iterable[Path]
) -> Path:
    """Where `dependency`'s source is copied in a build dir, to be rendered.

    Returns:
        The path of the copy, a `.j2` file next to its rendered output.
    """
    relative_path = dependency_relative_path(
        dependency.resolved_path, basedirs, dependency.variables_fingerprint
    )
    return (target_build_dir / relative_path).with_name(
        f"{relative_path.name}{dependency.resolved_path.suffix}.j2"
    )


@dataclass(frozen=True)
class CopiedDependency:
    build_path: Path
    """The build copy, a template rendered next to itself."""
    variables: Mapping[str, Any]
    source: Path
    """The content file it's a copy of."""


def copy_dependencies(
    dependencies: Iterable[DependencyRef],
    target_build_dir: Path,
    basedirs: Iterable[Path],
    *,
    force: bool = False,
) -> list[CopiedDependency]:
    copied = []
    for dependency in dependencies:
        build_path = build_copy_path(dependency, target_build_dir, basedirs)
        copy = CopiedDependency(
            build_path, dependency.variables, dependency.resolved_path
        )
        if force:
            build_path.parent.mkdir(parents=True, exist_ok=True)
            copyfile(dependency.resolved_path, build_path)
            copied.append(copy)
        elif copy_file_if_changed(dependency.resolved_path, build_path):
            _logger.debug("Re-rendering %s: new or changed", dependency.resolved_path)
            copied.append(copy)
    return copied


def _template_line(error: TemplateError, template: Path) -> int | None:
    # A syntax error carries its line; a runtime one (an undefined name, a
    # failing filter) is in the traceback, which Jinja points at the template.
    if isinstance(error, TemplateSyntaxError):
        return error.lineno
    frames = extract_tb(error.__traceback__)
    return next(
        (f.lineno for f in reversed(frames) if f.filename == str(template)), None
    )


def render_dependencies(
    renderer: RendererProtocol,
    markdown_converter: MarkdownConverterProtocol,
    to_render: Iterable[CopiedDependency],
    fragment_suffix: str,
) -> None:
    """Render each copied content file, and convert the Markdown ones.

    Raises:
        RenderError: Naming the content file and line, when Jinja fails.
    """
    for copied in to_render:
        item_path = copied.build_path
        rendered_path = item_path.with_suffix("")
        try:
            renderer.render_to_path(
                item_path, rendered_path, variables=copied.variables
            )
        except TemplateError as error:
            # Its copy now matches its source: without it, the next build
            # would take the file as rendered and keep its previous output.
            item_path.unlink(missing_ok=True)
            line = _template_line(error, item_path)
            where = f"{copied.source}:{line}" if line else str(copied.source)
            msg = f"{where}: {error.message or type(error).__name__}"
            raise RenderError(msg) from error
        if rendered_path.suffix == ".md":
            markdown_converter.convert(
                rendered_path, rendered_path.with_suffix(fragment_suffix)
            )


def _resolved_path(file: File) -> ResolvedPath:
    if file.resolved_path is None:
        # Parser.validate rejects such a deck before it gets here.
        msg = f"unresolved file {file.unresolved_path} ({file.parsing_error})"
        raise ValueError(msg)
    return file.resolved_path


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
                _resolved_path(file),
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
            _resolved_path(file), self._basedirs, fingerprint
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
