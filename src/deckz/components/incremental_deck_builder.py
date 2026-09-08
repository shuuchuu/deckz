import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from hashlib import sha256
from json import dumps, loads
from logging import ERROR, getLogger
from multiprocessing import Pool, cpu_count
from pathlib import Path, PurePosixPath
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import ArrayObject, NameObject, RectangleObject
from rich.progress import BarColumn, Progress, TaskID

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
)
from .compiler import CompileResult
from .deck_builder import (
    CompileType,
    copy_dependencies,
    render_dependencies,
    setup_build_dir,
)
from .protocols import CompilerProtocol, DeckBuilderProtocol, RendererProtocol

_INITIAL_COUNTERS: dict[str, int] = {"page": 1, "framenumber": 0}
_COUNTERS_LINE_RE = re.compile(r"^(\w+)\s+(-?\d+)\s*$")
_ZREF_POS_RE = re.compile(
    r"\\zref@newlabel\{deckz-toc-(\d+)\}\{\\posx\{-?\d+\}\\posy\{(-?\d+)\}\}"
)
_SP_PER_PT = 65536

# pypdf's PdfWriter.merge() logs "Annotation sizes differ" every time it
# clones a page carrying link annotations: it compares the not-yet-populated
# clone against the source page as an internal step, *before* copying the
# annotations over, so the mismatch it reports is expected and harmless, not
# a sign that anything was actually lost. It fires routinely here since our
# own ToC page carries link annotations we add ourselves (see
# _add_toc_links), and re-sourcing an unchanged skeleton from the previous
# build's output means merging that already-annotated page again.
getLogger("pypdf.generic._link").setLevel(ERROR)


def _hash_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _hash_text(text: str) -> str:
    return _hash_bytes(text.encode("utf8"))


def _fragment_key(relative_path: str) -> str:
    return _hash_bytes(relative_path.encode("utf8"))[:16]


########################################################################################
# Deck traversal: build an ordered timeline of titles and file fragments               #
########################################################################################


@dataclass(frozen=True)
class _FileRef:
    relative_path: str
    resolved_path: ResolvedPath


_TitleOrFile = Title | _FileRef


class _TimelineNodeVisitor(NodeVisitor[[list[_TitleOrFile], int], None]):
    def __init__(self, basedirs: Iterable[Path]) -> None:
        self._basedirs = tuple(basedirs)

    def process(self, deck: Deck) -> dict[PartName, list[_TitleOrFile]]:
        return {
            part_name: self._process_part(part)
            for part_name, part in deck.parts.items()
        }

    def _process_part(self, part: Part) -> list[_TitleOrFile]:
        items: list[_TitleOrFile] = []
        for node in part.nodes:
            node.accept(self, items, 0)
        return items

    def visit_file(self, file: File, items: list[_TitleOrFile], level: int) -> None:
        if file.title:
            items.append(Title(file.title, level))
        for basedir in self._basedirs:
            if file.resolved_path.is_relative_to(basedir):
                relative_path = file.resolved_path.relative_to(basedir).with_suffix("")
                break
        else:
            msg = f"could not find file {file}"
            raise ValueError(msg)
        items.append(_FileRef(str(PurePosixPath(relative_path)), file.resolved_path))

    def visit_section(
        self, section: Section, items: list[_TitleOrFile], level: int
    ) -> None:
        if section.title:
            items.append(Title(section.title, level))
            level += 1
        for node in section.nodes:
            node.accept(self, items, level)


@dataclass(frozen=True)
class _Fragment:
    key: str
    relative_path: str
    resolved_path: ResolvedPath
    # The section/subsection titles that must be (re-)issued right before this
    # fragment: only the ones not already established by the *previous*
    # fragment in the same part, so that batching consecutive fragments into
    # one compile never repeats a title verbatim (some themes insert a visible
    # divider frame on every \section/\subsection call, redundant or not).
    # Computed once here, from the part's own flat structure, so that a given
    # fragment always renders the same content regardless of which batch (if
    # any) it ends up grouped into — batch composition must never change what
    # a fragment looks like, only how many compiler invocations it costs.
    new_titles: tuple[Title, ...]
    # True when new_titles is this fragment's *entire* breadcrumb, i.e. it
    # doesn't rely on a preceding fragment having already established part of
    # it. A non-self-contained fragment must always be batched together with
    # whatever precedes it (see _group_into_batches): compiled on its own, it
    # would try to issue e.g. \subsection without a preceding \section, which
    # beamer/LaTeX rejects outright.
    self_contained: bool


@dataclass(frozen=True)
class _PartDivider:
    r"""A one-page "part starts here" frame, only emitted for multi-part items.

    Unlike a :class:`Title`, this produces an actual compiled page (it mirrors the
    template's ``%% if part.title != None: \begin{frame}[standout] ...`` block),
    so it is treated like a fragment by the build orchestration, while also acting
    like a top-level heading (level -1) for the outline and the printed ToC.
    """

    key: str
    title: str


# Timeline items that require their own compiled page(s): real file fragments and
# synthetic part-divider frames.
_Compilable = _Fragment | _PartDivider


@dataclass(frozen=True)
class _TocEntry:
    title: str
    level: int


_TimelineItem = Title | _Compilable


def _new_titles_suffix(
    previous: tuple[Title, ...], current: tuple[Title, ...]
) -> tuple[Title, ...]:
    # Identity, not value: two distinct Title occurrences with the same text
    # (e.g. the same section title used twice in a row) are still two
    # boundaries and must each be (re-)issued, matching the non-incremental
    # renderer, which is driven by document position, not text equality.
    common = 0
    while (
        common < len(previous)
        and common < len(current)
        and previous[common] is current[common]
    ):
        common += 1
    return current[common:]


def _build_timeline(flat_items: list[_TitleOrFile]) -> list[_TimelineItem]:
    timeline: list[_TimelineItem] = []
    breadcrumb: list[Title] = []
    occurrences: dict[str, int] = {}
    previous_fragment_breadcrumb: tuple[Title, ...] = ()
    for item in flat_items:
        if isinstance(item, Title):
            while breadcrumb and breadcrumb[-1].level >= item.level:
                breadcrumb.pop()
            breadcrumb.append(item)
            timeline.append(item)
        else:
            # The same file can legitimately be included several times in the same
            # item (e.g. reused across flavors), so the path alone isn't a unique
            # key: disambiguate by occurrence count, which only shifts when
            # occurrences of *this* path are themselves added/removed/reordered.
            occurrence = occurrences.get(item.relative_path, 0)
            occurrences[item.relative_path] = occurrence + 1
            current_breadcrumb = tuple(breadcrumb)
            new_titles = _new_titles_suffix(
                previous_fragment_breadcrumb, current_breadcrumb
            )
            timeline.append(
                _Fragment(
                    key=_fragment_key(f"{item.relative_path}#{occurrence}"),
                    relative_path=item.relative_path,
                    resolved_path=item.resolved_path,
                    new_titles=new_titles,
                    self_contained=new_titles == current_breadcrumb,
                )
            )
            previous_fragment_breadcrumb = current_breadcrumb
    return timeline


def _part_divider_key(part_name: str) -> str:
    return _fragment_key(f"part-divider#{part_name}")


########################################################################################
# Compile items                                                                        #
########################################################################################


@dataclass(frozen=True)
class _ItemSpec:
    name: str
    compile_type: CompileType
    # Whether the skeleton's ToC frame should be populated. The skeleton itself
    # (title page etc.) is always built: the real template's `\maketitle` isn't
    # gated behind this flag.
    show_toc: bool
    timeline: list[_TimelineItem]

    @property
    def fragments(self) -> list[_Fragment]:
        return [item for item in self.timeline if isinstance(item, _Fragment)]

    @property
    def compilables(self) -> list[_Compilable]:
        return [item for item in self.timeline if not isinstance(item, Title)]

    @property
    def toc_entries(self) -> list[_TocEntry]:
        # Sections only: no subsections (matches the non-incremental
        # renderer's \tableofcontents[subsectionstyle=hide]) and no part
        # dividers (legacy has no native way to track a manually-inserted
        # [standout] frame, since it isn't a LaTeX-level sectioning command
        # either). The PDF outline (sidebar bookmarks) is unrelated to this
        # and keeps full section/subsection depth (see _finalize_item),
        # exactly as hyperref's own bookmarks do in legacy mode regardless of
        # subsectionstyle.
        return [
            _TocEntry(item.title, item.level)
            for item in self.timeline
            if isinstance(item, Title) and item.level == 0
        ]


def _group_into_batches(
    stale_keys: set[str], compilables: list[_Compilable]
) -> list[list[_Compilable]]:
    # Group maximal runs of consecutive stale items: batching them into a single
    # compile job means the (potentially expensive) preamble is only loaded once
    # for the whole run, instead of once per fragment.
    included = [item.key in stale_keys for item in compilables]

    # A non-self-contained fragment relies on its immediate predecessor having
    # already issued part of its section/subsection breadcrumb: if it's being
    # recompiled, that predecessor must be pulled into the same batch too,
    # even if untouched, walking back further still if that one also isn't
    # self-contained. Otherwise the fragment would be compiled standalone
    # without the context it depends on.
    for index, item in enumerate(compilables):
        if not included[index] or not isinstance(item, _Fragment):
            continue
        if item.self_contained:
            continue
        previous_index = index - 1
        while previous_index >= 0:
            included[previous_index] = True
            previous_item = compilables[previous_index]
            if (
                isinstance(previous_item, _Fragment)
                and not previous_item.self_contained
            ):
                previous_index -= 1
            else:
                break

    batches: list[list[_Compilable]] = []
    current: list[_Compilable] = []
    for item, is_included in zip(compilables, included, strict=True):
        if is_included:
            current.append(item)
        elif current:
            batches.append(current)
            current = []
    if current:
        batches.append(current)
    return batches


########################################################################################
# Manifest: staleness bookkeeping persisted across runs                                #
########################################################################################


@dataclass
class _FragmentState:
    content_hash: str | None = None
    start_counters: dict[str, int] | None = None
    end_counters: dict[str, int] | None = None
    physical_page_count: int | None = None
    relative_path: str | None = None
    # Where this item's compiled pages currently live: the (possibly shared, if
    # this item was compiled as part of a batch) PDF file, and the 0-based index
    # of this item's first page within it.
    pdf_file: str | None = None
    page_start: int | None = None


@dataclass
class _ItemManifest:
    template_hash: str = ""
    variables_hash: str = ""
    toc_entries_hash: str = ""
    skeleton: _FragmentState = field(default_factory=_FragmentState)
    fragments: dict[str, _FragmentState] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "_ItemManifest":
        try:
            data = loads(path.read_text(encoding="utf8"))
            return cls(
                template_hash=data.get("template_hash", ""),
                variables_hash=data.get("variables_hash", ""),
                toc_entries_hash=data.get("toc_entries_hash", ""),
                skeleton=_FragmentState(**data.get("skeleton", {})),
                fragments={
                    key: _FragmentState(**value)
                    for key, value in data.get("fragments", {}).items()
                },
            )
        except (OSError, ValueError, TypeError):
            # Missing, corrupted, or produced by an older/incompatible manifest
            # schema: treat as if this were the first build for this item.
            return cls()

    def save(self, path: Path) -> None:
        data = {
            "template_hash": self.template_hash,
            "variables_hash": self.variables_hash,
            "toc_entries_hash": self.toc_entries_hash,
            "skeleton": vars(self.skeleton),
            "fragments": {key: vars(value) for key, value in self.fragments.items()},
        }
        path.write_text(dumps(data, indent=2), encoding="utf8")


def _counters_delta(start: dict[str, int], end: dict[str, int]) -> dict[str, int]:
    return {name: end[name] - start[name] for name in start}


def _apply_delta(counters: dict[str, int], delta: dict[str, int]) -> dict[str, int]:
    return {name: counters[name] + delta[name] for name in counters}


def _read_counters(path: Path) -> dict[str, int]:
    if not path.exists():
        msg = (
            f"{path} was not produced by the compilation: the template must write "
            "the counters (page, framenumber) to the expected path before "
            "\\end{document} (or at each part_checkpoints entry). See the "
            "incremental compilation documentation."
        )
        raise DeckzError(msg)
    counters: dict[str, int] = {}
    for line in path.read_text(encoding="utf8").splitlines():
        match = _COUNTERS_LINE_RE.match(line)
        if match:
            counters[match.group(1)] = int(match.group(2))
    missing = set(_INITIAL_COUNTERS) - set(counters)
    if missing:
        msg = f"{path} is missing counter(s) {sorted(missing)}"
        raise DeckzError(msg)
    return counters


def _read_toc_positions(aux_path: Path) -> dict[int, float]:
    if not aux_path.exists():
        return {}
    text = aux_path.read_text(encoding="utf8")
    return {
        int(index): int(posy) / _SP_PER_PT for index, posy in _ZREF_POS_RE.findall(text)
    }


########################################################################################
# Build orchestration                                                                  #
########################################################################################


@dataclass(frozen=True)
class _Job:
    item_name: str
    kind: str  # "skeleton" | "batch"
    tex_path: Path
    pdf_path: Path
    # skeleton jobs only:
    counters_path: Path | None = None
    # batch jobs only: ordered member keys, the counters the batch starts from,
    # and each member's own checkpoint file.
    members: tuple[str, ...] = ()
    start_counters: dict[str, int] | None = None
    checkpoint_paths: dict[str, Path] = field(default_factory=dict)


def _compile_job(args: tuple[CompilerProtocol, Path]) -> CompileResult:
    compiler, tex_path = args
    return compiler.compile(tex_path)


@dataclass
class _ItemWork:
    spec: _ItemSpec
    build_dir: Path
    old_manifest: _ItemManifest
    new_manifest: _ItemManifest
    globally_stale: bool
    content_hashes: dict[str, str]
    failed: bool = False


class IncrementalDeckBuilder(DeckBuilderProtocol):
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
    ) -> None:
        self._variables = variables
        self._build_presentation = build_presentation
        self._build_handout = build_handout
        self._build_print = build_print
        self._deck_name = deck.name
        self._output_dir = output_dir
        self._build_dir = build_dir
        self._dirs_to_link = dirs_to_link
        self._template = template
        self._basedirs = basedirs
        self._compiler = compiler
        self._renderer = renderer
        self._logger = getLogger(__name__)

        timelines = _TimelineNodeVisitor(basedirs).process(deck)
        self._per_part = {
            name: _build_timeline(flat) for name, flat in timelines.items()
        }
        self._part_titles = {name: part.title for name, part in deck.parts.items()}
        self._items = self._list_items()

    def _name_compile_item(
        self, compile_type: CompileType, name: PartName | None = None
    ) -> str:
        return (
            f"{self._deck_name}-{name}-{compile_type.value}"
            if name
            else f"{self._deck_name}-{compile_type.value}"
        ).lower()

    def _list_items(self) -> dict[str, _ItemSpec]:
        to_compile: dict[str, _ItemSpec] = {}
        # A part divider frame is only ever shown when a compile item bundles more
        # than one part together (matching the template's `parts | length > 1`
        # condition, which per-part items never satisfy).
        show_dividers = len(self._per_part) > 1
        all_timeline: list[_TimelineItem] = []
        for part_name, timeline in self._per_part.items():
            part_title = self._part_titles.get(part_name)
            if show_dividers and part_title:
                all_timeline.append(
                    _PartDivider(_part_divider_key(part_name), part_title)
                )
            all_timeline.extend(timeline)
        if self._build_handout:
            name = self._name_compile_item(CompileType.Handout)
            to_compile[name] = _ItemSpec(name, CompileType.Handout, True, all_timeline)
        if self._build_print:
            name = self._name_compile_item(CompileType.PrintHandout)
            to_compile[name] = _ItemSpec(name, CompileType.Handout, True, all_timeline)
        for part_name, timeline in self._per_part.items():
            if self._build_presentation:
                name = self._name_compile_item(CompileType.Presentation, part_name)
                to_compile[name] = _ItemSpec(
                    name, CompileType.Presentation, False, timeline
                )
            if self._build_handout:
                name = self._name_compile_item(CompileType.Handout, part_name)
                to_compile[name] = _ItemSpec(name, CompileType.Handout, False, timeline)
        return to_compile

    def build_deck(self) -> bool:
        template_hash = _hash_bytes(self._template.read_bytes())
        variables_hash = _hash_text(dumps(self._variables, sort_keys=True, default=str))

        works = {
            name: self._prepare_item(name, spec, template_hash, variables_hash)
            for name, spec in self._items.items()
        }

        round_1_jobs = self._plan_round_1(works)
        with Progress(
            "[progress.description]{task.description}",
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
        ) as progress:
            task_id = progress.add_task("Compiling…", total=len(round_1_jobs))
            ok = self._run_jobs(round_1_jobs, works, progress, task_id)
            round_2_jobs = self._plan_round_2(works)
            progress.update(task_id, total=len(round_1_jobs) + len(round_2_jobs))
            ok = self._run_jobs(round_2_jobs, works, progress, task_id) and ok

        for work in works.values():
            if not self._finalize_item(work):
                ok = False
        return ok

    def _prepare_item(
        self,
        name: str,
        spec: _ItemSpec,
        template_hash: str,
        variables_hash: str,
    ) -> _ItemWork:
        build_dir = setup_build_dir(self._build_dir, name, self._dirs_to_link)
        copied = copy_dependencies(
            {fragment.resolved_path for fragment in spec.fragments},
            build_dir,
            self._basedirs,
        )
        render_dependencies(self._renderer, copied)
        old_manifest = _ItemManifest.load(build_dir / "fragments.json")
        toc_entries_hash = _hash_text(
            dumps([[entry.title, entry.level] for entry in spec.toc_entries])
        )
        globally_stale = (
            old_manifest.template_hash != template_hash
            or old_manifest.variables_hash != variables_hash
        )
        content_hashes = {
            item.key: (
                _hash_bytes(item.resolved_path.read_bytes())
                if isinstance(item, _Fragment)
                else _hash_text(item.title)
            )
            for item in spec.compilables
        }
        return _ItemWork(
            spec=spec,
            build_dir=build_dir,
            old_manifest=old_manifest,
            new_manifest=_ItemManifest(
                template_hash=template_hash,
                variables_hash=variables_hash,
                toc_entries_hash=toc_entries_hash,
            ),
            globally_stale=globally_stale,
            content_hashes=content_hashes,
        )

    def _plan_round_1(self, works: dict[str, _ItemWork]) -> list[_Job]:
        jobs = []
        for work in works.values():
            # The skeleton (title page, and the ToC frame when show_toc is set) is
            # always built: the template's `\maketitle` isn't gated behind show_toc.
            skeleton_stale = (
                work.globally_stale
                or work.old_manifest.toc_entries_hash
                != work.new_manifest.toc_entries_hash
                or work.old_manifest.skeleton.end_counters is None
            )
            if skeleton_stale:
                guess = work.old_manifest.skeleton.start_counters or dict(
                    _INITIAL_COUNTERS
                )
                jobs.append(self._render_skeleton_job(work, guess))

            stale_keys = set()
            for item in work.spec.compilables:
                old_state = work.old_manifest.fragments.get(item.key)
                stale = (
                    work.globally_stale
                    or old_state is None
                    or old_state.content_hash != work.content_hashes[item.key]
                    or old_state.end_counters is None
                )
                if stale:
                    stale_keys.add(item.key)
            for batch in _group_into_batches(stale_keys, work.spec.compilables):
                old_state = work.old_manifest.fragments.get(batch[0].key)
                guess = (
                    old_state.start_counters
                    if old_state and old_state.start_counters is not None
                    else dict(_INITIAL_COUNTERS)
                )
                jobs.append(self._render_batch_job(work, batch, guess))
        return jobs

    def _plan_round_2(self, works: dict[str, _ItemWork]) -> list[_Job]:
        jobs = []
        for work in works.values():
            if work.failed:
                continue
            expected = dict(_INITIAL_COUNTERS)
            skeleton_state = work.new_manifest.skeleton
            if skeleton_state.end_counters is None:
                skeleton_state.content_hash = work.old_manifest.skeleton.content_hash
                skeleton_state.start_counters = (
                    work.old_manifest.skeleton.start_counters
                )
                skeleton_state.end_counters = work.old_manifest.skeleton.end_counters
                skeleton_state.physical_page_count = (
                    work.old_manifest.skeleton.physical_page_count
                )
            assert skeleton_state.start_counters is not None
            assert skeleton_state.end_counters is not None
            delta = _counters_delta(
                skeleton_state.start_counters, skeleton_state.end_counters
            )
            expected = _apply_delta(expected, delta)

            stale_keys: set[str] = set()
            expected_by_key: dict[str, dict[str, int]] = {}
            for item in work.spec.compilables:
                state = work.new_manifest.fragments.get(item.key)
                if state is None or state.end_counters is None:
                    old_state = work.old_manifest.fragments[item.key]
                    work.new_manifest.fragments[item.key] = old_state
                    state = old_state
                assert state.start_counters is not None
                assert state.end_counters is not None
                expected_by_key[item.key] = dict(expected)
                if state.start_counters != expected:
                    stale_keys.add(item.key)
                delta = _counters_delta(state.start_counters, state.end_counters)
                expected = _apply_delta(expected, delta)

            for batch in _group_into_batches(stale_keys, work.spec.compilables):
                start = expected_by_key[batch[0].key]
                jobs.append(self._render_batch_job(work, batch, start))
        return jobs

    def _render_skeleton_job(
        self, work: _ItemWork, start_counters: dict[str, int]
    ) -> _Job:
        base_name = f"{work.spec.name}-skeleton"
        tex_path = work.build_dir / f"{base_name}.tex"
        counters_path = work.build_dir / f"{base_name}.counters"
        toc_entries = [
            {"index": index, "title": entry.title, "level": entry.level}
            for index, entry in enumerate(work.spec.toc_entries)
        ]
        self._renderer.render_to_path(
            self._template,
            tex_path,
            **self._common_variables(work, start_counters),
            parts=[],
            toc=work.spec.show_toc,
            toc_entries=toc_entries,
            is_skeleton=True,
            counters_output_path=counters_path.name,
        )
        work.new_manifest.skeleton = _FragmentState(
            content_hash=work.new_manifest.toc_entries_hash,
            start_counters=dict(start_counters),
        )
        return _Job(
            item_name=work.spec.name,
            kind="skeleton",
            tex_path=tex_path,
            pdf_path=tex_path.with_suffix(".pdf"),
            counters_path=counters_path,
        )

    def _render_batch_job(
        self,
        work: _ItemWork,
        batch: list[_Compilable],
        start_counters: dict[str, int],
    ) -> _Job:
        batch_key = _hash_text("|".join(item.key for item in batch))[:16]
        base_name = f"{work.spec.name}-batch-{batch_key}"
        tex_path = work.build_dir / f"{base_name}.tex"

        parts = []
        checkpoint_paths: dict[str, Path] = {}
        part_checkpoints = []
        for item in batch:
            if isinstance(item, _Fragment):
                parts.append(
                    PartSlides(
                        title=None, sections=[*item.new_titles, item.relative_path]
                    )
                )
            else:
                parts.append(PartSlides(title=item.title, sections=[]))
            checkpoint_path = (
                work.build_dir / f"{base_name}-checkpoint-{item.key}.counters"
            )
            checkpoint_paths[item.key] = checkpoint_path
            part_checkpoints.append(checkpoint_path.name)

        self._renderer.render_to_path(
            self._template,
            tex_path,
            **self._common_variables(work, start_counters),
            parts=parts,
            part_checkpoints=part_checkpoints,
            toc=False,
            multi_part=True,
            is_skeleton=False,
        )

        for item in batch:
            work.new_manifest.fragments[item.key] = _FragmentState(
                content_hash=work.content_hashes[item.key],
                relative_path=(
                    item.relative_path
                    if isinstance(item, _Fragment)
                    else f"<part-divider:{item.title}>"
                ),
            )

        return _Job(
            item_name=work.spec.name,
            kind="batch",
            tex_path=tex_path,
            pdf_path=tex_path.with_suffix(".pdf"),
            members=tuple(item.key for item in batch),
            start_counters=dict(start_counters),
            checkpoint_paths=checkpoint_paths,
        )

    def _common_variables(
        self, work: _ItemWork, start_counters: dict[str, int]
    ) -> dict[str, Any]:
        handout = work.spec.compile_type in (
            CompileType.Handout,
            CompileType.PrintHandout,
        )
        is_print = work.spec.compile_type is CompileType.PrintHandout
        return {
            "variables": self._variables,
            "handout": handout,
            "print": is_print,
            "start_page": start_counters["page"],
            "start_framenumber": start_counters["framenumber"],
        }

    def _run_jobs(
        self,
        jobs: list[_Job],
        works: dict[str, _ItemWork],
        progress: Progress,
        task_id: TaskID,
    ) -> bool:
        if not jobs:
            return True
        ok = True
        with Pool(min(cpu_count(), len(jobs))) as pool:
            job_results = zip(
                jobs,
                pool.imap(
                    _compile_job, ((self._compiler, job.tex_path) for job in jobs)
                ),
                strict=True,
            )
            for job, result in job_results:
                self._apply_job_result(job, result, works)
                if not result.ok:
                    ok = False
                progress.update(task_id, advance=1)
        return ok

    def _apply_job_result(
        self, job: _Job, result: CompileResult, works: dict[str, _ItemWork]
    ) -> None:
        work = works[job.item_name]
        if not result.ok:
            work.failed = True
            self._logger.warning("Compilation of %s errored", job.tex_path.name)
            self._logger.warning("Captured stderr\n%s", result.stderr)
            self._logger.warning("Captured stdout\n%s", result.stdout)
            return
        if job.kind == "skeleton":
            assert job.counters_path is not None
            end_counters = _read_counters(job.counters_path)
            work.new_manifest.skeleton.end_counters = end_counters
            work.new_manifest.skeleton.physical_page_count = len(
                PdfReader(job.pdf_path).pages
            )
            return
        assert job.start_counters is not None
        running = dict(job.start_counters)
        page_index = 0
        for key in job.members:
            end_counters = _read_counters(job.checkpoint_paths[key])
            page_count = end_counters["page"] - running["page"]
            state = work.new_manifest.fragments[key]
            state.start_counters = dict(running)
            state.end_counters = end_counters
            state.physical_page_count = page_count
            state.pdf_file = job.pdf_path.name
            state.page_start = page_index
            page_index += page_count
            running = end_counters

    def _old_page_starts(self, work: _ItemWork) -> dict[str, int] | None:
        # Where each compilable's pages currently live within the *previous*
        # build's output PDF, so unchanged ones can be re-sourced from there
        # instead of from whatever (possibly long-superseded) batch file they
        # were originally compiled into. This keeps coalescing effective even
        # after many editing sessions have scattered a deck's fragments across
        # many small historical batch files.
        old_skeleton_count = work.old_manifest.skeleton.physical_page_count
        if old_skeleton_count is None:
            return None
        offset = old_skeleton_count
        starts: dict[str, int] = {}
        for item in work.spec.compilables:
            old_state = work.old_manifest.fragments.get(item.key)
            if old_state is None or old_state.physical_page_count is None:
                # This compilable (and, since positions are cumulative,
                # anything after it) didn't exist in the previous output in a
                # way we can trust the position of: fall back to fresh
                # sourcing from here on.
                break
            starts[item.key] = offset
            offset += old_state.physical_page_count
        return starts

    def _layout_timeline(
        self,
        work: _ItemWork,
        page_offset: int,
        old_page_starts: dict[str, int] | None,
        output_pdf_path: Path,
    ) -> tuple[list[tuple[str, int, int]], list[int], list[list[Any]]]:
        outline_entries: list[tuple[str, int, int]] = []
        toc_link_targets: list[int] = []
        # Page ranges to append, as [source_path, start, count], coalesced
        # across consecutive compilables that share the same underlying file
        # (e.g. a whole batch, several batches reused untouched back to back,
        # or a run of fragments re-sourced from the previous output). pypdf
        # recomputes named destinations from scratch on every append() call,
        # so merging what would otherwise be dozens of per-fragment calls into
        # a handful of calls over contiguous ranges avoids paying that cost
        # once per fragment.
        append_ranges: list[list[Any]] = []
        for item in work.spec.timeline:
            if isinstance(item, Title):
                # Every level goes in the PDF outline (matching hyperref's own
                # bookmarks in legacy mode, unaffected by subsectionstyle),
                # but only sections are toc_link_targets: it must mirror
                # _ItemSpec.toc_entries exactly, since _add_toc_links indexes
                # into it using the zsavepos label order that template loop
                # produced.
                outline_entries.append((item.title, item.level, page_offset))
                if item.level == 0:
                    toc_link_targets.append(page_offset)
                continue
            # _PartDivider falls through to the page-appending code below
            # (its frame is still real content that must be merged in), but
            # isn't indexed in the ToC or the PDF outline: legacy has no
            # native way to track a manually-inserted [standout] frame.
            new_state = work.new_manifest.fragments[item.key]
            assert new_state.pdf_file is not None
            assert new_state.page_start is not None
            assert new_state.physical_page_count is not None
            count = new_state.physical_page_count
            if (
                old_page_starts is not None
                and item.key in old_page_starts
                and work.old_manifest.fragments.get(item.key) == new_state
            ):
                source_path = output_pdf_path
                start = old_page_starts[item.key]
            else:
                source_path = work.build_dir / new_state.pdf_file
                start = new_state.page_start
            if (
                append_ranges
                and append_ranges[-1][0] == source_path
                and append_ranges[-1][1] + append_ranges[-1][2] == start
            ):
                append_ranges[-1][2] += count
            else:
                append_ranges.append([source_path, start, count])
            page_offset += count
        return outline_entries, toc_link_targets, append_ranges

    def _finalize_item(self, work: _ItemWork) -> bool:
        if work.failed:
            self._logger.warning(
                "Skipping assembly of %s because of compilation errors", work.spec.name
            )
            return False

        output_pdf_path = self._output_dir / f"{work.spec.name}.pdf"

        if work.new_manifest == work.old_manifest and output_pdf_path.exists():
            # Nothing at all changed for this item since the last successful
            # build: the existing output already reflects the current state
            # exactly, so there's no PDF work to redo.
            work.new_manifest.save(work.build_dir / "fragments.json")
            return True

        old_page_starts = (
            self._old_page_starts(work) if output_pdf_path.exists() else None
        )

        assert work.new_manifest.skeleton.physical_page_count is not None
        skeleton_count = work.new_manifest.skeleton.physical_page_count
        skeleton_unchanged = (
            old_page_starts is not None
            and work.old_manifest.skeleton == work.new_manifest.skeleton
        )
        skeleton_path = (
            output_pdf_path
            if skeleton_unchanged
            else work.build_dir / f"{work.spec.name}-skeleton.pdf"
        )

        writer = PdfWriter()
        readers: dict[Path, PdfReader] = {skeleton_path: PdfReader(skeleton_path)}
        writer.append(
            readers[skeleton_path], pages=(0, skeleton_count), import_outline=False
        )
        page_offset = skeleton_count

        outline_entries, toc_link_targets, append_ranges = self._layout_timeline(
            work, page_offset, old_page_starts, output_pdf_path
        )

        for source_path, start, count in append_ranges:
            reader = readers.get(source_path)
            if reader is None:
                reader = PdfReader(source_path)
                readers[source_path] = reader
            writer.append(reader, pages=(start, start + count), import_outline=False)

        parents: list[tuple[int, Any]] = []
        for title, level, target_page in outline_entries:
            while parents and parents[-1][0] >= level:
                parents.pop()
            parent_ref = parents[-1][1] if parents else None
            ref = writer.add_outline_item(title, target_page, parent=parent_ref)
            parents.append((level, ref))

        if work.spec.show_toc and toc_link_targets:
            self._add_toc_links(work, writer, toc_link_targets)

        self._output_dir.mkdir(parents=True, exist_ok=True)
        # Write to a temporary file and rename it into place atomically: the
        # readers above may include output_pdf_path itself (unchanged content
        # re-sourced from the previous build), so it must not be truncated or
        # modified until every page has actually been read from it.
        tmp_pdf_path = output_pdf_path.with_suffix(".pdf.tmp")
        with tmp_pdf_path.open("wb") as fh:
            writer.write(fh)
        tmp_pdf_path.replace(output_pdf_path)

        work.new_manifest.save(work.build_dir / "fragments.json")
        return True

    def _add_toc_links(
        self, work: _ItemWork, writer: PdfWriter, toc_link_targets: list[int]
    ) -> None:
        assert work.new_manifest.skeleton.physical_page_count is not None
        toc_page_index = work.new_manifest.skeleton.physical_page_count - 1
        positions = _read_toc_positions(
            work.build_dir / f"{work.spec.name}-skeleton.aux"
        )
        if not positions:
            return
        # The ToC page may have been re-sourced from the previous build's own
        # output (when the skeleton is unchanged), in which case it already
        # carries the link annotations added by *that* run: clear them before
        # adding this run's, or they'd stack up on every subsequent build.
        writer.pages[toc_page_index][NameObject("/Annots")] = ArrayObject()
        page_width = float(writer.pages[toc_page_index].mediabox.width)
        sorted_positions = sorted(positions.items())
        for i, (toc_index, y_pt) in enumerate(sorted_positions):
            if toc_index >= len(toc_link_targets):
                continue
            next_y = (
                sorted_positions[i + 1][1]
                if i + 1 < len(sorted_positions)
                else y_pt - 20
            )
            rect = RectangleObject((0, next_y + 5, page_width, y_pt + 15))
            link = Link(rect=rect, target_page_index=toc_link_targets[toc_index])
            writer.add_annotation(page_number=toc_page_index, annotation=link)
