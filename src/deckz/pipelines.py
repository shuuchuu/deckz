from collections.abc import Callable, Iterable, Set
from logging import getLogger
from pathlib import Path
from threading import Thread
from time import time
from typing import Any

from rich.progress import BarColumn, Progress
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .components.factory import DeckSettingsFactory, GlobalSettingsFactory
from .configuring.settings import DeckSettings, GlobalSettings
from .configuring.variables import get_variables
from .exceptions import DeckzError
from .models import Deck, FlavorName, PartName
from .utils import all_deck_settings

_logger = getLogger(__name__)


def _build(
    deck: Deck,
    settings: DeckSettings,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> bool:
    variables = get_variables(settings)
    factory = DeckSettingsFactory(settings)
    factory.assets_builder().build_assets()
    return factory.deck_builder(
        variables=variables,
        deck=deck,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    ).build_deck()


def run(
    settings: DeckSettings,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    parts_whitelist: Iterable[PartName] | None = None,
) -> None:
    parser = DeckSettingsFactory(settings).parser()
    deck = parser.from_deck_definition(settings.paths.deck_definition)
    if parts_whitelist is not None:
        deck.filter(parts_whitelist)
    _build(
        deck=deck,
        settings=settings,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    )


def run_file(
    latex: str,
    settings: DeckSettings,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    _build(
        deck=DeckSettingsFactory(settings).parser().from_file(latex),
        settings=settings,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    )


def run_section(
    section: str,
    flavor: FlavorName,
    settings: DeckSettings,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    _build(
        deck=DeckSettingsFactory(settings).parser().from_section(section, flavor),
        settings=settings,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    )


def run_all(
    directory: Path,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    global_settings = GlobalSettings.from_yaml(directory)
    GlobalSettingsFactory(global_settings).assets_builder().build_assets()
    decks_settings = list(all_deck_settings(global_settings.paths.git_dir))
    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
    ) as progress:
        task_id = progress.add_task("Building decks…", total=len(decks_settings))
        for deck_settings in decks_settings:
            result = _build(
                deck=DeckSettingsFactory(deck_settings)
                .parser()
                .from_deck_definition(deck_settings.paths.deck_definition),
                settings=deck_settings,
                build_handout=build_handout,
                build_presentation=build_presentation,
                build_print=build_print,
            )
            if not result:
                break
            progress.update(task_id, advance=1)


def run_assets(directory: Path) -> None:
    """Build all the project standalones (images, tikz, plots, etc).

    Args:
        directory: Path to the current directory. Will be used to find the project \
            directory
    """
    GlobalSettingsFactory(
        GlobalSettings.from_yaml(directory)
    ).assets_builder().build_assets()


class _BaseEventHandler(FileSystemEventHandler):
    def __init__[**P](
        self,
        minimum_delay: int,
        function: Callable[P, Any],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> None:
        self._minimum_delay = minimum_delay
        self._function = function
        self._function_args = args
        self._function_kwargs = kwargs
        self._last_compile = 0.0
        self._worker: Thread | None = None
        self._first_build = True

    def __call__(self) -> None:
        try:
            self._compiling = True
            if self._first_build:
                self._first_build = False
                _logger.info("Initial build")
            else:
                _logger.info("Detected changes, starting a new build")
            try:
                self._function(*self._function_args, **self._function_kwargs)
                _logger.info("Build finished")
            except Exception as e:
                _logger.exception(str(e), extra={"markup": True})
        finally:
            self._compiling = False

    def dispatch(self, event: FileSystemEvent) -> None:
        current_time = time()
        if self._last_compile + self._minimum_delay > current_time:
            return
        if self._worker is not None and self._worker.is_alive():
            _logger.info("Still on last build, not starting a new build")
            return
        self._last_compile = current_time
        self._worker = Thread(target=self.__call__)
        self._worker.start()


def watch[**P](
    minimum_delay: int,
    watch: Set[Path],
    avoid: Set[Path],
    function: Callable[P, Any],
    *function_args: P.args,
    **function_kwargs: P.kwargs,
) -> None:
    event_handler = _BaseEventHandler(
        minimum_delay, function, *function_args, **function_kwargs
    )
    observer = Observer()
    dirs_to_avoid = avoid | {
        r_to_avoid
        for dir_to_avoid in avoid
        for p in dir_to_avoid.rglob("*")
        if (r_to_avoid := p.resolve()).is_dir()
    }
    dirs_to_watch = watch | {
        r_to_watch
        for dir_to_watch in watch
        for p in dir_to_watch.rglob("*")
        if (r_to_watch := p.resolve()).is_dir() and r_to_watch not in dirs_to_avoid
    }
    for dir_to_watch in dirs_to_watch:
        observer.schedule(event_handler, str(dir_to_watch.resolve()), recursive=False)
    event_handler()
    observer.start()
    try:
        observer.join()
    except KeyboardInterrupt:
        observer.stop()
        observer.join()
        _logger.info("Stopped watching")
    else:
        observer.join()
        msg = "stopped watching abnormally"
        raise DeckzError(msg)
