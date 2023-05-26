from logging import getLogger
from pathlib import Path
from threading import Thread
from time import time
from typing import Any, Callable, FrozenSet, Optional

from watchdog.events import FileSystemEvent
from watchdog.observers import Observer

from .exceptions import DeckzException

_logger = getLogger(__name__)


class _BaseEventHandler:
    def __init__(
        self,
        minimum_delay: int,
        function: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ):
        self._minimum_delay = minimum_delay
        self._function = function
        self._function_args = args
        self._function_kwargs = kwargs
        self._last_compile = 0.0
        self._worker: Optional[Thread] = None
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
                _logger.error(str(e), extra=dict(markup=True))
        finally:
            self._compiling = False

    def dispatch(self, event: FileSystemEvent) -> None:
        current_time = time()
        if self._last_compile + self._minimum_delay > current_time:
            return
        elif self._worker is not None and self._worker.is_alive():
            _logger.info("Still on last build, not starting a new build")
            return
        else:
            self._last_compile = current_time
            self._worker = Thread(target=self.__call__)
            self._worker.start()


def watch(
    minimum_delay: int,
    watch: FrozenSet[Path],
    avoid: FrozenSet[Path],
    function: Callable[..., Any],
    *function_args: Any,
    **function_kwargs: Any,
) -> None:
    event_handler = _BaseEventHandler(
        minimum_delay, function, *function_args, **function_kwargs
    )
    observer = Observer()
    dirs_to_avoid = avoid | {
        r_to_avoid
        for dir_to_avoid in avoid
        for p in dir_to_avoid.glob("**/*")
        if (r_to_avoid := p.resolve()).is_dir()
    }
    dirs_to_watch = watch | {
        r_to_watch
        for dir_to_watch in watch
        for p in dir_to_watch.glob("**/*")
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
        raise DeckzException("Stopped watching abnormally")
