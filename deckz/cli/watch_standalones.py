from logging import getLogger
from pathlib import Path
from threading import Thread
from time import time
from typing import List, Optional

from watchdog.events import FileSystemEvent
from watchdog.observers import Observer

from deckz.cli import app
from deckz.exceptions import DeckzException
from deckz.paths import GlobalPaths
from deckz.running import run_standalones
from deckz.settings import Settings


_logger = getLogger(__name__)


class _LatexCompilerEventHandler:
    def __init__(self, minimum_delay: int, current_dir: Path, paths: GlobalPaths):
        self._minimum_delay = minimum_delay
        self._last_compile = 0.0
        self._current_dir = current_dir
        self._paths = paths
        self._worker: Optional[Thread] = None
        self._first_build = True

    def work(self) -> None:
        try:
            self._compiling = True
            if self._first_build:
                self._first_build = False
                _logger.info("Initial build")
            else:
                _logger.info("Detected changes, starting a new build")
            try:
                run_standalones(self._current_dir)
                _logger.info("Build finished")
            except Exception as e:
                _logger.critical("Build failed. Error: %s", str(e))
        finally:
            self._compiling = False

    def dispatch(self, event: FileSystemEvent) -> None:
        if self._paths.shared_tikz_pdf_dir in Path(event.src_path).parents:
            return
        current_time = time()
        if self._last_compile + self._minimum_delay > current_time:
            return
        elif self._worker is not None and self._worker.is_alive():
            _logger.info("Still on last build, not starting a new build")
            return
        else:
            self._last_compile = current_time
            self._worker = Thread(target=self.work)
            self._worker.start()


@app.command()
def watch_standalones(minimum_delay: int = 5, current_dir: Path = Path(".")) -> None:
    """Compile standalones on change."""
    _logger.info("Watching standalones directories")
    observer = Observer()
    paths = GlobalPaths.from_defaults(current_dir)
    settings = Settings(paths)
    event_handler = _LatexCompilerEventHandler(
        minimum_delay, current_dir=current_dir, paths=paths
    )
    paths_to_watch: List[Path] = []

    for d in settings.compile_standalones:
        paths_to_watch.extend(
            p for p in (paths.git_dir / d).glob("**/*") if p.resolve().is_dir()
        )
    for path in paths_to_watch:
        observer.schedule(event_handler, str(path.resolve()), recursive=False)
    event_handler.work()
    observer.start()
    try:
        while observer.isAlive():
            observer.join(1)
    except KeyboardInterrupt:
        observer.stop()
        observer.join()
        _logger.info("Stopped watching")
    else:
        observer.join()
        raise DeckzException("Stopped watching abnormally")
