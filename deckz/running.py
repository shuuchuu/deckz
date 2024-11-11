from collections.abc import Iterable
from logging import getLogger
from pathlib import Path

from rich import print as rich_print
from rich.progress import BarColumn, Progress

from .building.building import Builder
from .building.standalones import StandalonesBuilder
from .configuring.config import get_config
from .configuring.paths import GlobalPaths, Paths
from .configuring.settings import Settings
from .parsing.targets import Targets
from .parsing.tree_parsing import DeckParser
from .parsing.visitors.dependencies import build_dependencies
from .parsing.visitors.rich_tree import build_tree
from .parsing.visitors.titles_and_contents import build_targets_parts

_logger = getLogger(__name__)


def run(
    paths: Paths,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    target_whitelist: Iterable[str] | None = None,
) -> None:
    config = get_config(paths)
    # targets = Targets.from_file(paths=paths, whitelist=target_whitelist)
    deck = DeckParser(paths).parse()
    dependencies = build_dependencies(deck, paths)
    print(dependencies)
    # tree = build_tree(deck)
    # rich_print(tree)
    # parts = build_targets_parts(deck, paths)
    # print([i for t in targets.targets for i in t.parts])
    # print("*********************")
    # print(parts)
    # print(parts == [i for t in targets.targets for i in t.parts])
    # settings = Settings.from_global_paths(paths)
    # StandalonesBuilder(settings, paths).build()
    # Builder(
    #     config,
    #     settings,
    #     paths,
    #     targets,
    #     build_handout=build_handout,
    #     build_presentation=build_presentation,
    #     build_print=build_print,
    # ).build()


def run_file(
    latex: str,
    paths: Paths,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    config = get_config(paths)
    targets = Targets.from_data(
        [{"name": "section", "title": "section", "sections": [{"path": "latex"}]}],
        paths=paths,
    )
    settings = Settings.from_global_paths(paths)
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


def run_section(
    section: str,
    flavor: str,
    paths: Paths,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    config = get_config(paths)
    targets = Targets.from_data(
        [
            {
                "name": "section",
                "title": "section",
                "sections": [{"path": section, "flavor": flavor}],
            }
        ],
        paths=paths,
    )
    settings = Settings.from_global_paths(paths)
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
    directory: Path,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    paths = GlobalPaths.from_defaults(directory)
    settings = Settings.from_global_paths(paths)
    StandalonesBuilder(settings, paths).build()
    targets_paths = list(paths.git_dir.glob("**/targets.yml"))
    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
    ) as progress:
        task_id = progress.add_task("Building decks…", total=len(targets_paths))
        for target_paths in targets_paths:
            deck_paths = Paths.from_defaults(target_paths.parent)
            config = get_config(deck_paths)
            targets = Targets.from_file(paths=deck_paths)
            builder = Builder(
                config,
                settings,
                deck_paths,
                targets,
                build_handout=build_handout,
                build_presentation=build_presentation,
                build_print=build_print,
            )
            result = builder.build()
            if not result:
                break
            progress.update(task_id, advance=1)


def run_standalones(directory: Path) -> None:
    paths = GlobalPaths.from_defaults(directory)
    settings = Settings.from_global_paths(paths)
    standalones_builder = StandalonesBuilder(settings, paths)
    standalones_builder.build()
