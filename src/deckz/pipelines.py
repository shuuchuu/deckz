"""Build pipelines behind the `deckz run` commands.

Each command first computes its build targets (`*_targets`): the decks to \
compile, parsed once per language, with the settings to compile each with. \
`build` then compiles them, and `plan` (behind `--dry-run`) reports what `build` would \
do without doing any of it. The `run*` functions are `build` applied to \
their command's targets.
"""

from collections.abc import Callable, Generator, Iterable, Sequence, Set
from contextlib import contextmanager
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from time import perf_counter
from typing import Any

from watchfiles import watch as watchfiles_watch

from .checking import build_all_deck, build_shared_deck, run_scratch_dir
from .components.compiler import keep_warm
from .components.deck_builder import PlannedCompile
from .components.factory import DeckSettingsFactory, GlobalSettingsFactory
from .components.progress import NullProgress, PrefixedProgress
from .components.protocols import DeckBuilderProtocol, ProgressReporterProtocol
from .configuring.settings import DeckSettings, GlobalSettings
from .configuring.variables import get_variables
from .exceptions import (
    BuildFailure,
    BuildsFailedError,
    CompilationError,
    CourseNotesError,
    DeckzError,
)
from .models import Deck, FlavorName, Lang, PartName, lang_dir
from .utils import all_deck_settings, file_lock

_logger = getLogger(__name__)
_NULL_PROGRESS = NullProgress()


@dataclass(frozen=True)
class BuildTarget:
    """A parsed deck to compile, and the settings to compile it with."""

    deck: Deck
    settings: DeckSettings
    lang: Lang
    """The language `deck` was parsed in, and is to be compiled in."""
    label: str
    """Names the target in a compilation failure, e.g. the file previewed."""
    basedirs: tuple[Path, ...] | None = None
    """Where the deck's files live, when not just the usual content and deck \
    directories (see [`DeckSettingsFactory.deck_builder`]\
    [deckz.components.factory.DeckSettingsFactory.deck_builder])."""
    parts: tuple[PartName, ...] | None = None
    """The parts to compile, when not all of them (`--parts`). `deck` stays \
    whole: `stale_pdfs` needs every output of the deck, not only this build's."""
    course_notes: bool = False
    """`deck` is a deck's course notes (`course_notes_targets`): it compiles \
    to the course notes PDF only, whatever the build's other outputs."""


@dataclass(frozen=True)
class OutputKinds:
    """Which outputs to produce for each deck.

    PDFs, an HTML directory, and course notes (for `course_notes_targets`' \
    decks).
    """

    handout: bool
    presentation: bool
    print: bool
    html: bool = False
    part_handouts: bool = True
    """One handout per part, besides the whole deck's (with `handout` only)."""
    sync: bool = False
    """Remove the PDFs that no build of the decks produces anymore, in the \
    languages built (see `stale_pdfs`)."""
    course_notes: bool = False
    """Each deck's course notes too (`deck_targets`/`decks_targets` add \
    their targets), in `paths.course_notes_pdf_dir`, which `stale_pdfs` \
    never looks at."""

    @property
    def pdfs(self) -> bool:
        """Whether any PDF is built."""
        return self.handout or self.presentation or self.print


_EVERY_PDF = OutputKinds(handout=True, presentation=True, print=True)


def _deck_builder(
    target: BuildTarget,
    outputs: OutputKinds,
    progress: ProgressReporterProtocol,
    *,
    whole_deck: bool = False,
) -> DeckBuilderProtocol:
    lang = target.lang
    variables = {**get_variables(target.settings, lang=lang), "lang": lang}
    deck = (
        target.deck
        if whole_deck or target.parts is None
        else target.deck.filter(target.parts)
    )
    slides = not target.course_notes
    return DeckSettingsFactory(target.settings, lang=lang).deck_builder(
        variables=variables,
        deck=deck,
        build_handout=slides and outputs.handout,
        build_presentation=slides and outputs.presentation,
        build_print=slides and outputs.print,
        build_html=slides and outputs.html,
        build_part_handouts=outputs.part_handouts,
        basedirs=target.basedirs,
        progress=progress,
        build_course_notes=target.course_notes,
    )


def _compile_target(
    target: BuildTarget,
    outputs: OutputKinds,
    progress: ProgressReporterProtocol,
    *,
    keep_going: bool,
) -> BuildFailure | None:
    """Build one target.

    Returns:
        With `keep_going`, how it failed, if it did.

    Raises:
        CompilationError: When it fails to compile, without `keep_going`.
        DeckzError: When it fails before compiling (a content file's \
            render), without `keep_going`.
    """
    slides = outputs.pdfs or outputs.html
    if outputs.course_notes and not slides and not target.course_notes:
        return None  # Only the course notes were asked for.
    builder = _deck_builder(target, outputs, progress)
    with deck_lock(target.settings.paths.build_dir, target.label):
        try:
            built = builder.build_deck()
        except DeckzError as error:
            if not keep_going:
                raise
            return BuildFailure(target.label, target.lang, (("render", str(error)),))
    if built:
        return None
    if keep_going:
        return BuildFailure(target.label, target.lang, tuple(builder.failures()))
    msg = f"{target.label} failed to compile in {target.lang}, see the errors above"
    raise CompilationError(msg)


_REPORT_ERRORS_MAX = 6000
"""Characters of each failure's errors a report keeps: Typst's can run long."""


def _run_options(outputs: OutputKinds) -> str:
    # The `deckz run` options building what `outputs` asks for.
    flags = [
        "--handout" if outputs.handout else "--no-handout",
        "--presentation" if outputs.presentation else "--no-presentation",
        "--print" if outputs.print else "--no-print",
    ]
    if outputs.handout and not outputs.part_handouts:
        flags.append("--no-part-handouts")
    if outputs.html:
        flags.append("--html")
    return " ".join(flags)


def failure_report(
    failures: Sequence[BuildFailure], outputs: OutputKinds, what: str
) -> str:
    """A Markdown report of failed builds, for a person or an agent to fix.

    Args:
        failures: Each deck and language that failed, and why.
        outputs: What was built, to say how to build it again.
        what: What was built, e.g. "the decks changed since abc123".

    Returns:
        The report: each failure with the command reproducing it, from the \
        repository's root, and its errors (cut past `_REPORT_ERRORS_MAX` \
        characters).
    """
    lines = [
        f"# {len(failures)} deck build(s) failed",
        "",
        f"`deckz run decks` built {what}. Fix each build below so that its command"
        " succeeds, from the repository's root. Each error is the compiler's"
        " (Typst) or a content file's render, naming the file and line.",
    ]
    for failure in failures:
        lines += [
            "",
            f"## {failure.label}, in {failure.lang}",
            "",
            "```sh",
            f"deckz run --workdir {failure.label} --lang {failure.lang} "
            f"{_run_options(outputs)}",
            "```",
        ]
        for name, errors in failure.errors or (("build", "no error recorded"),):
            text = errors.strip()
            if len(text) > _REPORT_ERRORS_MAX:
                text = text[:_REPORT_ERRORS_MAX] + "\n[... cut: rerun the command]"
            lines += ["", f"{name}:", "", "```text", text, "```"]
    return "\n".join(lines) + "\n"


def build(
    targets: Sequence[BuildTarget],
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
    *,
    keep_going: bool = False,
) -> None:
    """Build the assets, then compile every target, stopping at the first failure.

    A target failing to compile raises a `CompilationError` naming it. Only \
    once every target compiled, `outputs.sync` removes the stale PDFs.

    Args:
        targets: What to build.
        outputs: The kinds of outputs to build.
        progress: Reports the decks' progress.
        keep_going: Build every target whatever fails, then raise a \
            `BuildsFailedError` with each failure (for a report of them all).

    Raises:
        BuildsFailedError: With `keep_going`, when some target failed.
    """
    if not targets:
        return
    # Every target belongs to the same repository, so to the same assets.
    start = perf_counter()
    DeckSettingsFactory(targets[0].settings).assets_builder().build_assets()
    _logger.debug("Built assets in %.2fs", perf_counter() - start)

    several_langs = len({target.lang for target in targets}) > 1

    def compile_target(target: BuildTarget) -> None:
        target_progress = (
            PrefixedProgress(progress, f"{target.lang}: ")
            if several_langs
            else progress
        )
        failure = _compile_target(
            target, outputs, target_progress, keep_going=keep_going
        )
        if failure is not None:
            failures.append(failure)

    failures: list[BuildFailure] = []
    # One deck, if in several languages, shows its compilations one language
    # after the other.
    if len({target.label for target in targets}) == 1:
        for target in targets:
            compile_target(target)
    else:
        with progress.track("Building decks…", len(targets)) as advance:
            for target in targets:
                compile_target(target)
                advance()
    if failures:
        failed = ", ".join(f"{f.label} ({f.lang})" for f in failures)
        msg = f"{len(failures)} build(s) failed: {failed}, see the errors above"
        raise BuildsFailedError(msg, failures)

    if outputs.sync:
        for pdf in stale_pdfs(targets, outputs):
            _logger.info("Removing %s, which no build of its deck produces", pdf)
            pdf.unlink()


@contextmanager
def deck_lock(build_dir: Path, label: str) -> Generator[None]:
    """One compilation of a deck's outputs at a time, across deckz processes.

    Two builds of one deck (a `--watch` and a full build, two terminals, an
    agent's build next to a person's) would write the same fragments and PDFs
    at once. The second one waits, saying so. The kernel releases the lock
    (`flock` on `<build_dir>/.lock`) when its process exits, however it exits.

    Args:
        build_dir: The deck's build directory.
        label: The deck, as the message waiting for it names it.

    Yields:
        Once the lock is held, until exiting.
    """
    with file_lock(
        build_dir / ".lock", f"Waiting for another build of {label} to finish"
    ):
        yield


def stale_pdfs(targets: Iterable[BuildTarget], outputs: OutputKinds) -> list[Path]:
    """The PDFs of `targets`' output directories that no build produces anymore.

    A PDF is stale when no build of its deck, whatever its kinds or parts, \
    would write it: a removed or renamed part's, a renamed deck's, a stray \
    file. What this build merely skips (presentations after a handout-only \
    build, other parts under `--parts`) is kept. Only the languages built \
    are looked at: another language's deck may not even parse. A build \
    producing no PDF at all (e.g. HTML only) leaves the PDFs alone.

    Args:
        targets: The build's targets.
        outputs: The build's outputs.

    Returns:
        The stale PDFs, sorted.
    """
    if not outputs.pdfs:
        return []
    expected: dict[Path, set[Path]] = {}
    for target in targets:
        if target.course_notes:
            continue
        directory = lang_dir(target.settings.paths.pdf_dir, target.lang)
        builder = _deck_builder(target, _EVERY_PDF, _NULL_PROGRESS, whole_deck=True)
        expected.setdefault(directory, set()).update(builder.output_paths())
    return sorted(
        pdf
        for directory, paths in expected.items()
        for pdf in directory.glob("*.pdf")
        if pdf not in paths
    )


def outdated_pdfs(targets: Iterable[BuildTarget]) -> list[Path]:
    """The PDFs of `targets`' output directories that don't match their content.

    Either no build of the deck produces them anymore (see `stale_pdfs`), \
    or a content fragment they include is new or changed since they were \
    built, or the Drive links they show (`deckz.drive_links`), or they were \
    never built here (no build directory, e.g. after `deckz clean`). Their \
    deck's yaml files and the main template aren't compared, only the \
    content fragments and the links. A course notes target's PDF is \
    compared too, but never stale.

    Returns:
        The outdated PDFs that exist, sorted.
    """
    targets = list(targets)
    outdated = set(stale_pdfs(targets, _EVERY_PDF))
    for target in targets:
        builder = _deck_builder(target, _EVERY_PDF, _NULL_PROGRESS, whole_deck=True)
        outdated.update(
            planned.output_path
            for planned in builder.plan()
            if planned.output_path.is_file()
            and (
                planned.full_render
                or planned.changed_fragments
                or planned.links_changed
            )
        )
    return sorted(outdated)


def published_targets(
    settings: DeckSettings, langs: Iterable[Lang]
) -> list[BuildTarget]:
    """What `deckz upload` publishes of the deck: slides and course notes.

    Args:
        settings: The deck's settings.
        langs: The languages to publish.

    Returns:
        One target per language, then the course notes', in the languages \
        they have chapters in.
    """
    langs = tuple(langs)
    return [
        *deck_targets(settings, langs),
        *course_notes_targets(settings, langs, required=False),
    ]


def published_pdfs(targets: Iterable[BuildTarget]) -> list[Path]:
    """Every PDF a full build of `targets` writes.

    Each kind, each part handout, and the course notes of their course \
    notes targets (`published_targets`): those a deck's Drive links \
    (`deckz.drive_links`) are reserved for.

    Returns:
        The PDFs, in build order.
    """
    return [
        path
        for target in targets
        for path in _deck_builder(
            target, _EVERY_PDF, _NULL_PROGRESS, whole_deck=True
        ).output_paths()
    ]


def plan(targets: Iterable[BuildTarget], outputs: OutputKinds) -> list[PlannedCompile]:
    """What `build` would compile and render, without building anything.

    Assets builders aren't run either: what they would regenerate is up to \
    the target repository's own code.

    Returns:
        One entry per output `build` would produce, in order.
    """
    return [
        planned
        for target in targets
        for planned in _deck_builder(target, outputs, _NULL_PROGRESS).plan()
    ]


def deck_targets(
    settings: DeckSettings,
    langs: Iterable[Lang],
    parts: Iterable[PartName] | None = None,
    *,
    course_notes: bool = False,
) -> list[BuildTarget]:
    """The deck of `settings`, restricted to `parts` if given.

    Args:
        settings: The deck's settings.
        langs: The languages to build it in.
        parts: The parts to build, all if None.
        course_notes: Add the deck's course notes, whole whatever `parts`, \
            in the languages they have chapters in (`course_notes_targets`).

    Returns:
        One target per language, then the course notes' if asked.
    """
    langs = tuple(langs)
    if course_notes:
        notes = course_notes_targets(settings, langs, required=False)
        if built := {target.lang for target in notes}:
            if skipped := [lang for lang in langs if lang not in built]:
                _logger.warning("No course notes chapter in %s yet", ", ".join(skipped))
        else:
            _logger.warning("No course notes chapter yet: only the slides are built")
        return [*deck_targets(settings, langs, parts), *notes]
    parts = None if parts is None else tuple(parts)
    targets = []
    for lang in langs:
        parser = DeckSettingsFactory(settings, lang=lang).parser()
        deck = parser.from_deck_definition(settings.paths.deck_definition)
        if parts is not None:
            # Fails now on an unknown part, before anything compiles.
            deck.filter(parts)
        targets.append(BuildTarget(deck, settings, lang, deck.name, parts=parts))
    return targets


def file_targets(
    path: str,
    settings: DeckSettings,
    langs: Iterable[Lang],
    *,
    course_notes: bool = False,
    required: bool = False,
) -> list[BuildTarget]:
    """A synthetic deck holding the single content file `path`.

    Args:
        path: The content file, relative to a content directory.
        settings: The settings to build it with (`checking.preview_settings`).
        langs: The languages to build it in.
        course_notes: Add its course notes chapter (`chapters_targets`).
        required: With `course_notes`, fail on a language with no chapter.

    Returns:
        One target per language, then its chapter's if asked.
    """
    targets = [
        BuildTarget(
            DeckSettingsFactory(settings, lang=lang).parser().from_file(path),
            settings,
            lang,
            path,
        )
        for lang in langs
    ]
    if course_notes:
        targets.extend(chapters_targets(targets, required=required))
    return targets


def section_targets(
    section: str,
    flavor: FlavorName,
    settings: DeckSettings,
    langs: Iterable[Lang],
    *,
    course_notes: bool = False,
    required: bool = False,
) -> list[BuildTarget]:
    """A synthetic deck holding `flavor` of `section`.

    Args:
        section: The shared section.
        flavor: Its flavor.
        settings: The settings to build it with (`checking.preview_settings`).
        langs: The languages to build it in.
        course_notes: Add its course notes chapters (`chapters_targets`).
        required: With `course_notes`, fail on a language with no chapter.

    Returns:
        One target per language, then its chapters' if asked.
    """
    targets = [
        BuildTarget(
            DeckSettingsFactory(settings, lang=lang)
            .parser()
            .from_section(section, flavor),
            settings,
            lang,
            f"{section}@{flavor}",
        )
        for lang in langs
    ]
    if course_notes:
        targets.extend(chapters_targets(targets, required=required))
    return targets


def decks_targets(
    directory: Path,
    langs: Iterable[Lang],
    *,
    course_notes: bool = False,
    since: str | None = None,
) -> list[BuildTarget]:
    """Every deck of the repository containing `directory`.

    All are parsed up front, in every language, so a broken deck fails the \
    command before any compilation starts.

    Args:
        directory: A directory of the repository.
        langs: The languages to build the decks in.
        course_notes: Add each deck's course notes, in the languages it has \
            chapters in (`course_notes_targets`).
        since: Only the decks the changes since this revision (and the \
            working tree's) reach (`affected_since`).

    Returns:
        One target per deck and language, then the course notes' if asked.
    """
    from .analyzing.affected import affected_since

    langs = tuple(langs)
    git_dir = GlobalSettings.from_yaml(directory).paths.git_dir
    all_settings = (
        affected_since(git_dir, since)
        if since is not None
        else list(all_deck_settings(git_dir))
    )
    targets = []
    for lang in langs:
        for settings in all_settings:
            parser = DeckSettingsFactory(settings, lang=lang).parser()
            deck = parser.from_deck_definition(settings.paths.deck_definition)
            label = str(settings.paths.current_dir.relative_to(git_dir))
            targets.append(BuildTarget(deck, settings, lang, label))
    if course_notes:
        notes = [
            target
            for settings in all_settings
            for target in course_notes_targets(settings, langs, required=False)
        ]
        _logger.info(
            "Course notes of the %d deck(s) with chapters",
            len({target.label for target in notes}),
        )
        targets.extend(notes)
    return targets


COURSE_NOTES = OutputKinds(
    handout=False, presentation=False, print=False, course_notes=True
)


def chapters_required(outputs: OutputKinds) -> bool:
    """Whether a preview building `outputs` fails on a language with no chapter.

    Returns:
        True when the course notes are all it builds: else, the slides are \
        built all the same.
    """
    return outputs.course_notes and not (outputs.pdfs or outputs.html)


def course_notes_targets(
    settings: DeckSettings, langs: Iterable[Lang], *, required: bool = True
) -> list[BuildTarget]:
    """The course notes of the deck of `settings` (`course_notes.chapters_deck`).

    Args:
        settings: The deck's settings.
        langs: The languages to build them in.
        required: Fail on a language with no chapter written at all; else \
            leave it out.

    Returns:
        One target per language.

    Raises:
        CourseNotesError: If `required` and a language has no chapter written \
            at all.
    """
    paths = settings.paths
    targets = []
    for lang in langs:
        parser = DeckSettingsFactory(settings, lang=lang).parser()
        deck = parser.from_deck_definition(paths.deck_definition)
        notes = _chapters_target(BuildTarget(deck, settings, lang, deck.name))
        if notes is None:
            msg = (
                f"{deck.name} has no course notes chapter in {lang} yet, under "
                f"{paths.course_notes_dir.relative_to(paths.git_dir)}"
            )
            if required:
                raise CourseNotesError(msg)
            continue
        targets.append(notes)
    return targets


def _chapters_target(target: BuildTarget) -> BuildTarget | None:
    # `target`'s course notes, if any of its files has a chapter written.
    from .course_notes import chapters_deck

    settings = target.settings
    paths = settings.paths
    chapters = chapters_deck(settings, target.deck, target.lang)
    if not chapters.parts:
        return None
    basedirs = (paths.course_notes_dir, paths.assets_dir, paths.current_dir)
    label = f"{target.label} course notes"
    return BuildTarget(
        chapters, settings, target.lang, label, basedirs, course_notes=True
    )


def chapters_targets(
    targets: Iterable[BuildTarget], *, required: bool = False
) -> list[BuildTarget]:
    """The course notes of `targets`' decks: their chapters (`chapters_deck`).

    For a `run file`/`run section` preview: a chapter builds with the course \
    notes' main template, whether a deck includes its content file or not.

    Args:
        targets: The previews' targets, one per language.
        required: Fail on a language with no chapter; else leave it out, \
            with a warning.

    Returns:
        One target per language with a chapter.

    Raises:
        CourseNotesError: If `required` and a language has no chapter.
    """
    notes = []
    for target in targets:
        if (chapters := _chapters_target(target)) is not None:
            notes.append(chapters)
            continue
        paths = target.settings.paths
        where = paths.course_notes_dir.relative_to(paths.git_dir)
        if required:
            msg = (
                f"{target.label} has no course notes chapter in {target.lang} "
                f"yet, under {where}"
            )
            raise CourseNotesError(msg)
        _logger.warning(
            "%s has no course notes chapter in %s yet, under %s: only its slides "
            "are built",
            target.label,
            target.lang,
            where,
        )
    return notes


def run_course_notes(
    settings: DeckSettings,
    langs: Iterable[Lang],
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    build(course_notes_targets(settings, langs), COURSE_NOTES, progress)


def shared_targets(directory: Path, langs: Iterable[Lang]) -> list[BuildTarget]:
    """Every shared section, each expanded to all its files (`run shared`).

    Returns:
        One target per language, built under `<git_dir>/.run/shared/`.
    """
    git_dir = GlobalSettings.from_yaml(directory).paths.git_dir
    settings = DeckSettings.from_yaml(run_scratch_dir(git_dir, "shared"))
    targets = []
    for lang in langs:
        deck = build_shared_deck(settings, lang)
        targets.append(
            BuildTarget(deck, settings, lang, deck.name, basedirs=(git_dir,))
        )
    return targets


def all_targets(directory: Path, langs: Iterable[Lang]) -> list[BuildTarget]:
    """`shared_targets`' deck plus every deck-local override (`run all`).

    Returns:
        One target per language, built under `<git_dir>/.run/all/`.
    """
    git_dir = GlobalSettings.from_yaml(directory).paths.git_dir
    settings = DeckSettings.from_yaml(run_scratch_dir(git_dir, "all"))
    targets = []
    for lang in langs:
        deck = build_all_deck(settings, lang)
        targets.append(
            BuildTarget(deck, settings, lang, deck.name, basedirs=(git_dir,))
        )
    return targets


def run(
    settings: DeckSettings,
    langs: Iterable[Lang],
    outputs: OutputKinds,
    parts: Iterable[PartName] | None = None,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    targets = deck_targets(settings, langs, parts, course_notes=outputs.course_notes)
    build(targets, outputs, progress)


def run_file(
    path: str,
    settings: DeckSettings,
    langs: Iterable[Lang],
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    targets = file_targets(
        path,
        settings,
        langs,
        course_notes=outputs.course_notes,
        required=chapters_required(outputs),
    )
    build(targets, outputs, progress)


def run_section(
    section: str,
    flavor: FlavorName,
    settings: DeckSettings,
    langs: Iterable[Lang],
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    targets = section_targets(
        section,
        flavor,
        settings,
        langs,
        course_notes=outputs.course_notes,
        required=chapters_required(outputs),
    )
    build(targets, outputs, progress)


def run_decks(
    directory: Path,
    langs: Iterable[Lang],
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    targets = decks_targets(directory, langs, course_notes=outputs.course_notes)
    build(targets, outputs, progress)


def run_shared(
    directory: Path,
    langs: Iterable[Lang],
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    build(shared_targets(directory, langs), outputs, progress)


def run_all(
    directory: Path,
    langs: Iterable[Lang],
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    build(all_targets(directory, langs), outputs, progress)


def run_assets(directory: Path) -> None:
    """Build all the project standalones (images, plots, etc).

    Args:
        directory: Path to the current directory. Will be used to find the project \
            directory
    """
    GlobalSettingsFactory(
        GlobalSettings.from_yaml(directory)
    ).assets_builder().build_assets()


def watch[**P](
    watch: Set[Path],
    avoid: Set[Path],
    function: Callable[P, Any],
    *function_args: P.args,
    **function_kwargs: P.kwargs,
) -> None:
    dirs_to_avoid = avoid | {
        p.resolve() for dir_to_avoid in avoid for p in dir_to_avoid.glob("**")
    }

    dirs_to_watch = watch | {
        r_to_watch
        for dir_to_watch in watch
        for p in dir_to_watch.glob("**")
        if (r_to_watch := p.resolve()) not in dirs_to_avoid
    }
    _logger.info("Watching:\n%s", "\n".join(sorted(str(d) for d in dirs_to_watch)))
    # Keeps a Typst worker process alive per compiled PDF, so every rebuild
    # after the first is incremental.
    with keep_warm():
        _watch_loop(dirs_to_watch, function, *function_args, **function_kwargs)


def _watch_loop[**P](
    dirs_to_watch: Set[Path],
    function: Callable[P, Any],
    *function_args: P.args,
    **function_kwargs: P.kwargs,
) -> None:
    _logger.info("Initial build")
    _run_once("Initial build finished", function, *function_args, **function_kwargs)

    for _ in watchfiles_watch(*dirs_to_watch, raise_interrupt=False, recursive=False):
        _logger.info("Detected changes, starting a new build")
        _run_once("Build finished", function, *function_args, **function_kwargs)


def _run_once[**P](
    success_message: str,
    function: Callable[P, Any],
    *function_args: P.args,
    **function_kwargs: P.kwargs,
) -> None:
    # A failed build must not end the watch: report it and wait for the next
    # change. User errors get their message only, bugs keep their traceback.
    try:
        function(*function_args, **function_kwargs)
        _logger.info(success_message)
    except DeckzError as e:
        _logger.error(str(e))
    except Exception as e:
        _logger.exception(str(e), extra={"markup": True})
