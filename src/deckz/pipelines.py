"""Build pipelines behind the `deckz run` commands.

Each command first computes its build targets (`*_targets`): the decks to \
compile, parsed once per language, with the settings to compile each with. \
`build` then compiles them, and `plan` (behind `--dry-run`) reports what `build` would \
do without doing any of it. The `run*` functions are `build` applied to \
their command's targets.
"""

from collections.abc import Callable, Iterable, Iterator, Sequence, Set
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
from .configuring.variables import get_variables, resolve_variables
from .exceptions import CompilationError, DeckzError
from .models import Deck, FlavorName, Lang, PartName, lang_dir
from .utils import all_deck_settings

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


@dataclass(frozen=True)
class OutputKinds:
    """Which outputs to produce for each deck: PDFs, and an HTML directory."""

    handout: bool
    presentation: bool
    print: bool
    html: bool = False
    part_handouts: bool = True
    """One handout per part, besides the whole deck's (with `handout` only)."""
    sync: bool = False
    """Remove the PDFs that no build of the decks produces anymore, in the \
    languages built (see `stale_pdfs`)."""

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
    return DeckSettingsFactory(target.settings, lang=lang).deck_builder(
        variables=variables,
        deck=resolve_variables(deck, variables),
        build_handout=outputs.handout,
        build_presentation=outputs.presentation,
        build_print=outputs.print,
        build_html=outputs.html,
        build_part_handouts=outputs.part_handouts,
        basedirs=target.basedirs,
        progress=progress,
    )


def build(
    targets: Sequence[BuildTarget],
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    """Build the assets, then compile every target, stopping at the first failure.

    A target failing to compile raises a `CompilationError` naming it. Only \
    once every target compiled, `outputs.sync` removes the stale PDFs.
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
        builder = _deck_builder(target, outputs, target_progress)
        with deck_lock(target.settings.paths.build_dir, target.label):
            built = builder.build_deck()
        if not built:
            msg = (
                f"{target.label} failed to compile in {target.lang}, see the "
                "errors above"
            )
            raise CompilationError(msg)

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

    if outputs.sync:
        for pdf in stale_pdfs(targets, outputs):
            _logger.info("Removing %s, which no build of its deck produces", pdf)
            pdf.unlink()


@contextmanager
def deck_lock(build_dir: Path, label: str) -> Iterator[None]:
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
    import fcntl

    build_dir.mkdir(parents=True, exist_ok=True)
    with (build_dir / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _logger.info("Waiting for another build of %s to finish", label)
            fcntl.flock(lock, fcntl.LOCK_EX)
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
    built, or they were never built here (no build directory, e.g. after \
    `deckz clean`). Their deck's yaml files and the main template aren't \
    compared, only the content fragments.

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
            and (planned.full_render or planned.changed_fragments)
        )
    return sorted(outdated)


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
) -> list[BuildTarget]:
    """The deck of `settings`, restricted to `parts` if given.

    Returns:
        One target per language.
    """
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
    path: str, settings: DeckSettings, langs: Iterable[Lang]
) -> list[BuildTarget]:
    """A synthetic deck holding the single content file `path`.

    Returns:
        One target per language.
    """
    return [
        BuildTarget(
            DeckSettingsFactory(settings, lang=lang).parser().from_file(path),
            settings,
            lang,
            path,
        )
        for lang in langs
    ]


def section_targets(
    section: str, flavor: FlavorName, settings: DeckSettings, langs: Iterable[Lang]
) -> list[BuildTarget]:
    """A synthetic deck holding `flavor` of `section`.

    Returns:
        One target per language.
    """
    return [
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


def decks_targets(directory: Path, langs: Iterable[Lang]) -> list[BuildTarget]:
    """Every deck of the repository containing `directory`.

    All are parsed up front, in every language, so a broken deck fails the \
    command before any compilation starts.

    Returns:
        One target per deck and language.
    """
    git_dir = GlobalSettings.from_yaml(directory).paths.git_dir
    all_settings = list(all_deck_settings(git_dir))
    targets = []
    for lang in langs:
        for settings in all_settings:
            parser = DeckSettingsFactory(settings, lang=lang).parser()
            deck = parser.from_deck_definition(settings.paths.deck_definition)
            label = str(settings.paths.current_dir.relative_to(git_dir))
            targets.append(BuildTarget(deck, settings, lang, label))
    return targets


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
    build(deck_targets(settings, langs, parts), outputs, progress)


def run_file(
    path: str,
    settings: DeckSettings,
    langs: Iterable[Lang],
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    build(file_targets(path, settings, langs), outputs, progress)


def run_section(
    section: str,
    flavor: FlavorName,
    settings: DeckSettings,
    langs: Iterable[Lang],
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    build(section_targets(section, flavor, settings, langs), outputs, progress)


def run_decks(
    directory: Path,
    langs: Iterable[Lang],
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    build(decks_targets(directory, langs), outputs, progress)


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
