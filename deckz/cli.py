from argparse import ArgumentParser
from logging import getLogger
from pathlib import Path
from shutil import copy as shutil_copy
from threading import Lock
from time import time
from typing import Any, Callable, List, NamedTuple, Optional

from watchdog.events import FileSystemEvent
from watchdog.observers import Observer

from deckz.builder import build
from deckz.config import get_config
from deckz.paths import paths
from deckz.targets import Dependencies, Targets


_logger = getLogger(__name__)


class Command(NamedTuple):
    name: str
    description: str
    handler: Callable[..., Any]
    parser_definer: Callable[[ArgumentParser], None]


commands: List[Command] = []


def register_command(
    parser_definer: Callable[[ArgumentParser], None] = lambda _: None,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def wrapper(handler: Callable[..., Any]) -> Callable[..., Any]:
        commands.append(
            Command(
                name=handler.__name__.replace("_", "-") if name is None else name,
                description=handler.__doc__.strip().splitlines()[0]
                if description is None
                else description,
                parser_definer=parser_definer,
                handler=handler,
            )
        )
        return handler

    return wrapper


def _define_run_parser(parser: ArgumentParser) -> None:
    parser.add_argument(
        "targets",
        nargs="*",
        help="Targets to restrict to. No argument = consider everything.",
    )
    parser.add_argument(
        "--no-handout",
        dest="handout",
        action="store_false",
        help="Don't compile the handout.",
    )
    parser.add_argument(
        "--no-presentation",
        dest="presentation",
        action="store_false",
        help="Don't compile the presentation.",
    )
    parser.add_argument(
        "--verbose-latexmk", action="store_true", help="Make latexmk verbose."
    )


@register_command(parser_definer=_define_run_parser)
def run(
    targets: List[str], handout: bool, presentation: bool, verbose_latexmk: bool
) -> None:
    """Compile main targets."""
    _run(
        handout=handout,
        presentation=presentation,
        verbose_latexmk=verbose_latexmk,
        debug=False,
        target_whitelist=targets,
    )


def _define_debug_parser(parser: ArgumentParser) -> None:
    parser.add_argument(
        "targets",
        nargs="*",
        help="Targets to restrict to. No argument = consider everything.",
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


@register_command(parser_definer=_define_debug_parser)
def debug(
    targets: List[str], handout: bool, presentation: bool, verbose_latexmk: bool
) -> None:
    """Compile debug targets."""
    _run(
        handout=handout,
        presentation=presentation,
        verbose_latexmk=verbose_latexmk,
        debug=True,
        target_whitelist=targets if targets else None,
    )


def _run(
    handout: bool,
    presentation: bool,
    verbose_latexmk: bool,
    debug: bool,
    target_whitelist: List[str],
) -> None:
    config = get_config()
    targets = Targets(debug=debug, fail_on_missing=True, whitelist=target_whitelist)
    for i, target in enumerate(targets, start=1):
        if handout:
            _logger.info(f"Building handout for target {i}/{len(targets)}")
            build(
                config=config,
                target=target,
                handout=True,
                verbose_latexmk=verbose_latexmk,
            )
        if presentation:
            _logger.info(f"Building presentation for target {i}/{len(targets)}")
            build(
                config=config,
                target=target,
                handout=False,
                verbose_latexmk=verbose_latexmk,
            )


def _define_watch_parser(parser: ArgumentParser) -> None:
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
        help="Minimum delay before recompiling.",
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


@register_command(parser_definer=_define_watch_parser)
def watch(
    minimum_delay: int,
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
            handout: bool,
            presentation: bool,
            verbose_latexmk: bool,
            debug: bool,
            target_whitelist: List[str],
        ):
            self._minimum_delay = minimum_delay
            self._last_compile = 0.0
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
                    _logger.info("Still on last build, not starting a new build")
                    return
                else:
                    self._last_compile = current_time
            try:
                self._compiling = True
                _logger.info("Detected changes, starting a new build")
                _run(
                    handout=self._handout,
                    presentation=self._presentation,
                    verbose_latexmk=self._verbose_latexmk,
                    debug=self._debug,
                    target_whitelist=self._target_whitelist,
                )
            finally:
                self._compiling = False

    _logger.info(f"Watching current and shared directories")
    observer = Observer()
    event_handler = LatexCompilerEventHandler(
        minimum_delay,
        handout=handout,
        presentation=presentation,
        verbose_latexmk=verbose_latexmk,
        debug=debug,
        target_whitelist=target_whitelist,
    )
    observer.schedule(event_handler, str(paths.shared_dir), recursive=True)
    observer.schedule(event_handler, str(paths.working_dir), recursive=True)
    observer.start()
    try:
        while observer.isAlive():
            observer.join(1)
    except KeyboardInterrupt:
        observer.stop()
        observer.join()
        _logger.info("Quitting")
        exit(0)
    observer.join()
    _logger.info("Stopped watching current and shared directories")
    exit(1)


@register_command()
def fill() -> None:
    """Fill the dependency directories with templates for missing targets."""

    if paths.targets.exists():
        if paths.targets_debug.exists():
            dependencies = Dependencies.merge(
                Targets(
                    debug=False, fail_on_missing=False, whitelist=[]
                ).get_dependencies(),
                Targets(
                    debug=True, fail_on_missing=False, whitelist=[]
                ).get_dependencies(),
            )
        else:
            dependencies = Targets(
                debug=False, fail_on_missing=False, whitelist=[]
            ).get_dependencies()
    elif paths.targets_debug.exists():
        dependencies = Targets(
            debug=True, fail_on_missing=False, whitelist=[]
        ).get_dependencies()
    else:
        _logger.critical("Could not find any target file.")
        exit(1)
    if dependencies.missing:
        _logger.info(
            "Creating the following missing dependencies:\n%s",
            "\n".join(f"  - {str(d)}" for d in sorted(dependencies.missing)),
        )
        for dependency in dependencies.missing:
            dependency.parent.mkdir(exist_ok=True, parents=True)
            shutil_copy(str(paths.template_latex), str(dependency))
    else:
        _logger.info("All targets have a matching LaTeX files")


@register_command()
def init() -> None:
    """Create an initial targets.yml."""

    if paths.targets.exists():
        _logger.info(f"Nothing to do: {paths.targets} already exists")

    else:
        _logger.info(f"Copying {paths.template_targets} to current directory")
        shutil_copy(str(paths.template_targets), str(paths.working_dir))


@register_command()
def print_config() -> None:
    """Print the resolved configuration."""
    config = get_config()
    _logger.info(
        "Resolved config as:\n%s",
        "\n".join((f"  - {k}: {v}") for k, v in config.items()),
    )


def _define_clean_latex_parser(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would be removed.",
    )


@register_command(parser_definer=_define_clean_latex_parser)
def clean_latex(dry_run: bool) -> None:
    """Clean LaTeX files that are not used in `targets*.yml`."""

    _logger.info(f"Cleaning unused LaTeX files")
    dependencies = Dependencies.merge(
        Targets(debug=False, fail_on_missing=False, whitelist=[]).get_dependencies(),
        Targets(debug=True, fail_on_missing=False, whitelist=[]).get_dependencies(),
    )
    if dependencies.unused:
        _logger.info(
            "%s the following unused dependencies:\n%s",
            "Would remove" if dry_run else "Removing",
            "\n".join(f"  - {str(d)}" for d in sorted(dependencies.unused)),
        )
    else:
        _logger.info("All LaTeX files are used, nothing to remove")
    if not dry_run:
        for dependency in dependencies.unused:
            dependency.unlink()
