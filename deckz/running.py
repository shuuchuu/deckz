from logging import getLogger
from pathlib import Path
from typing import List, Optional

from ray import get, init, is_initialized, ObjectRef, wait
from rich.progress import BarColumn, Progress

from deckz.building import Builder, RemoteBuilder
from deckz.config import get_config
from deckz.paths import GlobalPaths, Paths
from deckz.settings import Settings
from deckz.standalones import StandalonesBuilder
from deckz.targets import Targets


_logger = getLogger(__name__)


def run(
    paths: Paths,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    target_whitelist: Optional[List[str]] = None,
) -> None:
    if not is_initialized():
        init()
    config = get_config(paths)
    targets = Targets.from_file(paths=paths, whitelist=target_whitelist)
    settings = Settings(paths)
    StandalonesBuilder(settings, paths).build()
    Builder(
        config,
        settings,
        paths,
        targets,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    ).build()


def run_all(
    directory: Path, build_handout: bool, build_presentation: bool, build_print: bool,
) -> None:
    def run(targets_path: Path) -> ObjectRef:
        deck_paths = Paths.from_defaults(targets_path.parent)
        config = get_config(deck_paths)
        targets = Targets.from_file(paths=deck_paths)
        builder = RemoteBuilder.remote(  # type: ignore
            config,
            settings,
            deck_paths,
            targets,
            build_handout=build_handout,
            build_presentation=build_presentation,
            build_print=build_print,
        )
        get(builder.setup_logging.remote())
        return builder.build.remote()

    if not is_initialized():
        init()
    max_actors = 3
    paths = GlobalPaths.from_defaults(directory)
    settings = Settings(paths)
    StandalonesBuilder(settings, paths).build()
    targets_paths = list(paths.git_dir.glob("**/targets.yml"))
    total = len(targets_paths)
    builds = [run(targets_path) for targets_path in targets_paths[:max_actors]]
    targets_paths = targets_paths[max_actors:]
    ok = True
    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
    ) as progress:
        task_id = progress.add_task("Building decks…", total=total)
        while targets_paths or builds:
            [done], builds = wait(builds)
            ok &= get(done)
            progress.update(task_id, advance=1)
            if targets_paths:
                builds.append(run(targets_paths.pop()))
    assert not builds


def run_standalones(directory: Path) -> None:
    if not is_initialized():
        init()
    paths = GlobalPaths.from_defaults(directory)
    settings = Settings(paths)
    standalones_builder = StandalonesBuilder(settings, paths)
    standalones_builder.build()
