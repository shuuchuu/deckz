from collections.abc import Iterable
from pathlib import Path
from sys import stderr

from rich import print as rich_print
from rich.progress import BarColumn, Progress

from .building.building import Builder
from .building.standalones import StandalonesBuilder
from .configuring.config import get_config
from .configuring.paths import GlobalPaths, Paths
from .configuring.settings import Settings
from .deck_building import DeckBuilder
from .exceptions import DeckzError
from .models.deck import Deck
from .models.scalars import FlavorName, PartName
from .processing.part_dependencies import PartDependenciesProcessor
from .processing.rich_tree import RichTreeProcessor
from .processing.titles_and_contents import SlidesProcessor
from .utils import all_paths


def _build(
    deck: Deck,
    paths: Paths,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> bool:
    config = get_config(paths)
    tree = RichTreeProcessor().process(deck)
    if tree is not None:
        rich_print(tree, file=stderr)
        msg = "deck parsing failed"
        raise DeckzError(msg)
    dependencies = PartDependenciesProcessor().process(deck)
    parts_slides = SlidesProcessor(paths.shared_dir, paths.current_dir).process(deck)
    settings = Settings.from_global_paths(paths)
    StandalonesBuilder(settings, paths).build()
    return Builder(
        latex_config=config,
        settings=settings,
        paths=paths,
        deck_name=deck.acronym,
        parts_slides=parts_slides,
        dependencies=dependencies,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    ).build()


def run(
    paths: Paths,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    parts_whitelist: Iterable[PartName] | None = None,
) -> None:
    deck = DeckBuilder(paths.local_latex_dir, paths.shared_latex_dir).from_targets(
        paths.deck_config, paths.targets
    )
    if parts_whitelist is not None:
        deck.filter(parts_whitelist)
    _build(
        deck=deck,
        paths=paths,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    )


def run_file(
    latex: str,
    paths: Paths,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    deck = DeckBuilder(paths.local_latex_dir, paths.shared_latex_dir).from_file(latex)
    _build(
        deck=deck,
        paths=paths,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    )


def run_section(
    section: str,
    flavor: FlavorName,
    paths: Paths,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    deck = DeckBuilder(paths.local_latex_dir, paths.shared_latex_dir).from_section(
        section, flavor
    )
    _build(
        deck=deck,
        paths=paths,
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
    global_paths = GlobalPaths(current_dir=directory)
    settings = Settings.from_global_paths(global_paths)
    StandalonesBuilder(settings, global_paths).build()
    deck_paths = list(all_paths(global_paths.git_dir))
    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
    ) as progress:
        task_id = progress.add_task("Building decks…", total=len(deck_paths))
        for paths in deck_paths:
            deck = DeckBuilder(
                paths.local_latex_dir, paths.shared_latex_dir
            ).from_targets(paths.deck_config, paths.targets)
            result = _build(
                deck=deck,
                paths=paths,
                build_handout=build_handout,
                build_presentation=build_presentation,
                build_print=build_print,
            )
            if not result:
                break
            progress.update(task_id, advance=1)


def run_standalones(directory: Path) -> None:
    paths = GlobalPaths(current_dir=directory)
    settings = Settings.from_global_paths(paths)
    standalones_builder = StandalonesBuilder(settings, paths)
    standalones_builder.build()
