"""Build pipelines behind the `deckz run` commands.

Each command first computes its build targets (`*_targets`): the decks to \
compile, parsed, with the settings to compile each with. `build` then \
compiles them, and `plan` (behind `--dry-run`) reports what `build` would \
do without doing any of it. The `run*` functions are `build` applied to \
their command's targets.
"""

from collections.abc import Callable, Iterable, Sequence, Set
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
from .components.progress import NullProgress
from .components.protocols import DeckBuilderProtocol, ProgressReporterProtocol
from .configuring.settings import DeckSettings, GlobalSettings
from .configuring.variables import get_variables, resolve_variables
from .exceptions import CompilationError, DeckzError
from .models import Deck, FlavorName, Lang, PartName
from .utils import all_deck_settings

_logger = getLogger(__name__)
_NULL_PROGRESS = NullProgress()


@dataclass(frozen=True)
class BuildTarget:
    """A parsed deck to compile, and the settings to compile it with."""

    deck: Deck
    settings: DeckSettings
    label: str
    """Names the target in a compilation failure, e.g. the file previewed."""
    basedirs: tuple[Path, ...] | None = None
    """Where the deck's files live, when not just the usual content and deck \
    directories (see [`DeckSettingsFactory.deck_builder`]\
    [deckz.components.factory.DeckSettingsFactory.deck_builder])."""


@dataclass(frozen=True)
class OutputKinds:
    """Which PDFs to produce for each deck."""

    handout: bool
    presentation: bool
    print: bool


def _deck_builder(
    target: BuildTarget,
    lang: Lang,
    outputs: OutputKinds,
    progress: ProgressReporterProtocol,
) -> DeckBuilderProtocol:
    variables = {**get_variables(target.settings, lang=lang), "lang": lang}
    return DeckSettingsFactory(target.settings, lang=lang).deck_builder(
        variables=variables,
        deck=resolve_variables(target.deck, variables),
        build_handout=outputs.handout,
        build_presentation=outputs.presentation,
        build_print=outputs.print,
        basedirs=target.basedirs,
        progress=progress,
    )


def build(
    targets: Sequence[BuildTarget],
    lang: Lang,
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    """Build the assets, then compile every target, stopping at the first failure.

    A target failing to compile raises a `CompilationError` naming it.
    """
    if not targets:
        return
    # Every target belongs to the same repository, so to the same assets.
    start = perf_counter()
    DeckSettingsFactory(targets[0].settings, lang=lang).assets_builder().build_assets()
    _logger.debug("Built assets in %.2fs", perf_counter() - start)

    def compile_target(target: BuildTarget) -> None:
        if not _deck_builder(target, lang, outputs, progress).build_deck():
            msg = f"{target.label} failed to compile, see the errors above"
            raise CompilationError(msg)

    if len(targets) == 1:
        compile_target(targets[0])
        return
    with progress.track("Building decks…", len(targets)) as advance:
        for target in targets:
            compile_target(target)
            advance()


def plan(
    targets: Iterable[BuildTarget], lang: Lang, outputs: OutputKinds
) -> list[PlannedCompile]:
    """What `build` would compile and render, without building anything.

    Assets builders aren't run either: what they would regenerate is up to \
    the target repository's own code.

    Returns:
        One entry per PDF `build` would produce, in order.
    """
    return [
        planned
        for target in targets
        for planned in _deck_builder(target, lang, outputs, _NULL_PROGRESS).plan()
    ]


def deck_targets(
    settings: DeckSettings, lang: Lang, parts: Iterable[PartName] | None = None
) -> list[BuildTarget]:
    """The deck of `settings`, restricted to `parts` if given.

    Returns:
        The single target.
    """
    parser = DeckSettingsFactory(settings, lang=lang).parser()
    deck = parser.from_deck_definition(settings.paths.deck_definition)
    if parts is not None:
        deck = deck.filter(parts)
    return [BuildTarget(deck, settings, deck.name)]


def file_targets(path: str, settings: DeckSettings, lang: Lang) -> list[BuildTarget]:
    """A synthetic deck holding the single content file `path`.

    Returns:
        The single target.
    """
    deck = DeckSettingsFactory(settings, lang=lang).parser().from_file(path)
    return [BuildTarget(deck, settings, path)]


def section_targets(
    section: str, flavor: FlavorName, settings: DeckSettings, lang: Lang
) -> list[BuildTarget]:
    """A synthetic deck holding `flavor` of `section`.

    Returns:
        The single target.
    """
    parser = DeckSettingsFactory(settings, lang=lang).parser()
    deck = parser.from_section(section, flavor)
    return [BuildTarget(deck, settings, f"{section}@{flavor}")]


def decks_targets(directory: Path, lang: Lang) -> list[BuildTarget]:
    """Every deck of the repository containing `directory`.

    All are parsed up front, so a broken deck fails the command before any \
    compilation starts.

    Returns:
        One target per deck.
    """
    git_dir = GlobalSettings.from_yaml(directory).paths.git_dir
    targets = []
    for settings in all_deck_settings(git_dir):
        parser = DeckSettingsFactory(settings, lang=lang).parser()
        deck = parser.from_deck_definition(settings.paths.deck_definition)
        label = str(settings.paths.current_dir.relative_to(git_dir))
        targets.append(BuildTarget(deck, settings, label))
    return targets


def shared_targets(directory: Path, lang: Lang) -> list[BuildTarget]:
    """Every shared section, each expanded to all its files (`run shared`).

    Returns:
        The single target, built under `<git_dir>/.run/shared/`.
    """
    git_dir = GlobalSettings.from_yaml(directory).paths.git_dir
    settings = DeckSettings.from_yaml(run_scratch_dir(git_dir, "shared"))
    deck = build_shared_deck(settings, lang)
    return [BuildTarget(deck, settings, deck.name, basedirs=(git_dir,))]


def all_targets(directory: Path, lang: Lang) -> list[BuildTarget]:
    """`shared_targets`' deck plus every deck-local override (`run all`).

    Returns:
        The single target, built under `<git_dir>/.run/all/`.
    """
    git_dir = GlobalSettings.from_yaml(directory).paths.git_dir
    settings = DeckSettings.from_yaml(run_scratch_dir(git_dir, "all"))
    deck = build_all_deck(settings, lang)
    return [BuildTarget(deck, settings, deck.name, basedirs=(git_dir,))]


def run(
    settings: DeckSettings,
    lang: Lang,
    outputs: OutputKinds,
    parts: Iterable[PartName] | None = None,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    build(deck_targets(settings, lang, parts), lang, outputs, progress)


def run_file(
    path: str,
    settings: DeckSettings,
    lang: Lang,
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    build(file_targets(path, settings, lang), lang, outputs, progress)


def run_section(
    section: str,
    flavor: FlavorName,
    settings: DeckSettings,
    lang: Lang,
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    build(section_targets(section, flavor, settings, lang), lang, outputs, progress)


def run_decks(
    directory: Path,
    lang: Lang,
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    build(decks_targets(directory, lang), lang, outputs, progress)


def run_shared(
    directory: Path,
    lang: Lang,
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    build(shared_targets(directory, lang), lang, outputs, progress)


def run_all(
    directory: Path,
    lang: Lang,
    outputs: OutputKinds,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    build(all_targets(directory, lang), lang, outputs, progress)


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
