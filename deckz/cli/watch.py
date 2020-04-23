from argparse import ArgumentParser
from logging import getLogger
from pathlib import Path
from threading import Lock
from time import time
from typing import List

from watchdog.events import FileSystemEvent
from watchdog.observers import Observer

from deckz.cli import register_command
from deckz.exceptions import DeckzException
from deckz.paths import Paths
from deckz.runner import run


def _parser_definer(parser: ArgumentParser) -> None:
    parser.add_argument(
        "target_whitelist",
        nargs="*",
        metavar="targets",
        help="Targets to restrict to. No argument = consider everything.",
    )
    parser.add_argument(
        "--minimum-delay",
        type=int,
        default=5,
        help="Minimum delay before recompiling, defaults to `%(default)s`.",
    )
    parser.add_argument(
        "--no-debug",
        dest="debug",
        action="store_false",
        help="Use main targets, not debug targets.",
    )
    parser.add_argument(
        "--handout", action="store_true", help="Compile the handout.",
    )
    parser.add_argument(
        "--no-presentation",
        dest="presentation",
        action="store_false",
        help="Don't compile the presentation.",
    )
    parser.add_argument(
        "--silent-latexmk",
        dest="verbose_latexmk",
        action="store_false",
        help="Make latexmk silent.",
    )
    parser.add_argument(
        "--deck-path",
        dest="paths",
        type=Paths,
        default=".",
        help="Path of the deck, defaults to `%(default)s`.",
    )


@register_command(parser_definer=_parser_definer)
def watch(
    minimum_delay: int,
    paths: Paths,
    handout: bool,
    presentation: bool,
    verbose_latexmk: bool,
    debug: bool,
    target_whitelist: List[str],
) -> None:
    """Compile on change."""

    class LatexCompilerEventHandler:
        def __init__(
            self,
            minimum_delay: int,
            paths: Paths,
            handout: bool,
            presentation: bool,
            verbose_latexmk: bool,
            debug: bool,
            target_whitelist: List[str],
        ):
            self._minimum_delay = minimum_delay
            self._last_compile = 0.0
            self._paths = paths
            self._handout = handout
            self._presentation = presentation
            self._verbose_latexmk = verbose_latexmk
            self._debug = debug
            self._target_whitelist = target_whitelist
            self._lock = Lock()
            self._compiling = False

        def dispatch(self, event: FileSystemEvent) -> None:
            try:
                Path(event.src_path).relative_to(paths.build_dir)
            except ValueError:
                pass
            else:
                return
            with self._lock:
                current_time = time()
                if self._last_compile + self._minimum_delay > current_time:
                    return
                elif self._compiling:
                    logger.info("Still on last build, not starting a new build")
                    return
                else:
                    self._last_compile = current_time
            try:
                self._compiling = True
                logger.info("Detected changes, starting a new build")
                try:
                    run(
                        paths=self._paths,
                        handout=self._handout,
                        presentation=self._presentation,
                        verbose_latexmk=self._verbose_latexmk,
                        debug=self._debug,
                        target_whitelist=self._target_whitelist,
                    )
                except Exception as e:
                    logger.critical("Build failed. Error: %s", str(e))
            finally:
                self._compiling = False

    logger = getLogger(__name__)
    logger.info(f"Watching current and shared directories")
    observer = Observer()
    event_handler = LatexCompilerEventHandler(
        minimum_delay,
        paths=paths,
        handout=handout,
        presentation=presentation,
        verbose_latexmk=verbose_latexmk,
        debug=debug,
        target_whitelist=target_whitelist,
    )
    paths_to_watch = [
        (p, False) for p in paths.shared_dir.glob("**/*") if p.resolve().is_dir()
    ]
    paths_to_watch.append((paths.jinja2_dir, True))
    paths_to_watch.append((paths.working_dir, True))
    for path, recursive in paths_to_watch:
        observer.schedule(event_handler, str(path.resolve()), recursive=recursive)
    observer.start()
    try:
        while observer.isAlive():
            observer.join(1)
    except KeyboardInterrupt:
        observer.stop()
        observer.join()
        logger.info("Stopped watching")
    else:
        observer.join()
        raise DeckzException("Stopped watching abnormally")
