from collections.abc import Callable, Iterable, Set
from logging import getLogger
from pathlib import Path
from time import perf_counter
from typing import Any

from watchfiles import watch as watchfiles_watch

from .checking import build_all_deck, build_shared_deck, run_scratch_dir
from .components.compiler import keep_warm
from .components.factory import DeckSettingsFactory, GlobalSettingsFactory
from .components.progress import NullProgress
from .components.protocols import ProgressReporterProtocol
from .configuring.settings import DeckSettings, GlobalSettings
from .configuring.variables import get_variables, resolve_variables
from .exceptions import CompilationError, DeckzError
from .models import Deck, FlavorName, Lang, PartName
from .utils import all_deck_settings

_logger = getLogger(__name__)
_NULL_PROGRESS = NullProgress()


def _build(
    deck: Deck,
    settings: DeckSettings,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    progress: ProgressReporterProtocol,
    basedirs: tuple[Path, ...] | None = None,
) -> None:
    variables = {**get_variables(settings, lang=lang), "lang": lang}
    factory = DeckSettingsFactory(settings, lang=lang)
    start = perf_counter()
    factory.assets_builder().build_assets()
    _logger.debug("Built assets in %.2fs", perf_counter() - start)
    if not factory.deck_builder(
        variables=variables,
        deck=resolve_variables(deck, variables),
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
        basedirs=basedirs,
        progress=progress,
    ).build_deck():
        msg = f"{deck.name} failed to compile, see the errors above"
        raise CompilationError(msg)


def run(
    settings: DeckSettings,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    parts_whitelist: Iterable[PartName] | None = None,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    parser = DeckSettingsFactory(settings, lang=lang).parser()
    deck = parser.from_deck_definition(settings.paths.deck_definition)
    if parts_whitelist is not None:
        deck = deck.filter(parts_whitelist)
    _build(
        deck=deck,
        settings=settings,
        lang=lang,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
        progress=progress,
    )


def run_file(
    path: str,
    settings: DeckSettings,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    try:
        _build(
            deck=DeckSettingsFactory(settings, lang=lang).parser().from_file(path),
            settings=settings,
            lang=lang,
            build_handout=build_handout,
            build_presentation=build_presentation,
            build_print=build_print,
            progress=progress,
        )
    except CompilationError as e:
        # The synthetic preview deck is named "deck": name what was asked for.
        msg = f"{path} failed to compile, see the errors above"
        raise CompilationError(msg) from e


def run_section(
    section: str,
    flavor: FlavorName,
    settings: DeckSettings,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    try:
        _build(
            deck=DeckSettingsFactory(settings, lang=lang)
            .parser()
            .from_section(section, flavor),
            settings=settings,
            lang=lang,
            build_handout=build_handout,
            build_presentation=build_presentation,
            build_print=build_print,
            progress=progress,
        )
    except CompilationError as e:
        # The synthetic preview deck is named "deck": name what was asked for.
        msg = f"{section}@{flavor} failed to compile, see the errors above"
        raise CompilationError(msg) from e


def run_decks(
    directory: Path,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    global_settings = GlobalSettings.from_yaml(directory)
    GlobalSettingsFactory(global_settings).assets_builder().build_assets()
    decks_settings = list(all_deck_settings(global_settings.paths.git_dir))
    with progress.track("Building decks…", len(decks_settings)) as advance:
        for deck_settings in decks_settings:
            try:
                _build(
                    deck=DeckSettingsFactory(deck_settings, lang=lang)
                    .parser()
                    .from_deck_definition(deck_settings.paths.deck_definition),
                    settings=deck_settings,
                    lang=lang,
                    build_handout=build_handout,
                    build_presentation=build_presentation,
                    build_print=build_print,
                    progress=progress,
                )
            except CompilationError as e:
                deck_dir = deck_settings.paths.current_dir.relative_to(
                    global_settings.paths.git_dir
                )
                msg = f"{deck_dir} failed to compile, see the errors above"
                raise CompilationError(msg) from e
            advance()


def run_shared(
    directory: Path,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    global_settings = GlobalSettings.from_yaml(directory)
    git_dir = global_settings.paths.git_dir
    GlobalSettingsFactory(global_settings).assets_builder().build_assets()
    settings = DeckSettings.from_yaml(run_scratch_dir(git_dir, "shared"))
    deck = build_shared_deck(settings, lang)
    _build(
        deck=deck,
        settings=settings,
        lang=lang,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
        progress=progress,
        basedirs=(git_dir,),
    )


def run_all(
    directory: Path,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    progress: ProgressReporterProtocol = _NULL_PROGRESS,
) -> None:
    global_settings = GlobalSettings.from_yaml(directory)
    git_dir = global_settings.paths.git_dir
    GlobalSettingsFactory(global_settings).assets_builder().build_assets()
    settings = DeckSettings.from_yaml(run_scratch_dir(git_dir, "all"))
    deck = build_all_deck(settings, lang)
    _build(
        deck=deck,
        settings=settings,
        lang=lang,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
        progress=progress,
        basedirs=(git_dir,),
    )


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
