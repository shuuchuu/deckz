from pathlib import Path
from typing import List, Optional

from rich.progress import track

from deckz.building import Builder
from deckz.config import get_config
from deckz.paths import GlobalPaths, Paths
from deckz.settings import Settings
from deckz.standalones import StandalonesBuilder
from deckz.targets import Targets


def run(
    paths: Paths,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    target_whitelist: Optional[List[str]] = None,
) -> None:
    config = get_config(paths)
    targets = Targets.from_file(paths=paths, whitelist=target_whitelist)
    settings = Settings(paths)
    builder = Builder(
        config,
        settings,
        paths,
        targets,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    )
    builder.build()


def run_all(
    directory: Path, build_handout: bool, build_presentation: bool, build_print: bool,
) -> None:
    paths = GlobalPaths.from_defaults(directory)
    for targets in track(list(paths.git_dir.glob("**/targets.yml"))):
        targets_paths = Paths.from_defaults(targets.parent)
        run(
            targets_paths,
            build_handout=build_handout,
            build_presentation=build_presentation,
            build_print=build_print,
        )


def run_standalones(directory: Path) -> None:
    paths = GlobalPaths.from_defaults(directory)
    settings = Settings(paths)
    standalones_builder = StandalonesBuilder(settings, paths)
    standalones_builder.build()
