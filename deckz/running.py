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
from .exceptions import DeckzError
from .parsing.tree_parsing import (
    Deck,
    DeckParser,
    FileInclude,
    PartDefinition,
    SectionInclude,
)
from .parsing.visitors.dependencies import DependenciesVisitor
from .parsing.visitors.rich_tree import RichTreeVisitor
from .parsing.visitors.titles_and_contents import SlidesVisitor


def _build(
    deck: Deck,
    paths: Paths,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> bool:
    config = get_config(paths)
    tree = RichTreeVisitor().process_deck(deck)
    if tree is not None:
        rich_print(tree, file=stderr)
        msg = "deck parsing failed"
        raise DeckzError(msg)
    dependencies = DependenciesVisitor().process_deck(deck)
    parts_slides = SlidesVisitor(paths).process_deck(deck)
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
    target_whitelist: Iterable[str] | None = None,
) -> None:
    deck = DeckParser(paths).parse()
    if target_whitelist is not None:
        deck.filter(target_whitelist)
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
    deck = Deck(
        acronym="deck",
        parts=DeckParser(paths).parse_parts(
            [
                PartDefinition.model_construct(
                    name="part_name",
                    sections=[FileInclude(path=Path(latex))],
                )
            ]
        ),
    )
    _build(
        deck=deck,
        paths=paths,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    )


def run_section(
    section: str,
    flavor: str,
    paths: Paths,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    deck = Deck(
        acronym="deck",
        parts=DeckParser(paths).parse_parts(
            [
                PartDefinition.model_construct(
                    name="part_name",
                    sections=[SectionInclude(path=Path(section), flavor=flavor)],
                )
            ]
        ),
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
    paths = GlobalPaths.from_defaults(directory)
    settings = Settings.from_global_paths(paths)
    StandalonesBuilder(settings, paths).build()
    targets_paths = list(paths.git_dir.rglob("targets.yml"))
    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
    ) as progress:
        task_id = progress.add_task("Building decks…", total=len(targets_paths))
        for target_paths in targets_paths:
            deck_paths = Paths.from_defaults(target_paths.parent)
            deck = DeckParser(deck_paths).parse()
            result = _build(
                deck=deck,
                paths=deck_paths,
                build_handout=build_handout,
                build_presentation=build_presentation,
                build_print=build_print,
            )
            if not result:
                break
            progress.update(task_id, advance=1)


def run_standalones(directory: Path) -> None:
    paths = GlobalPaths.from_defaults(directory)
    settings = Settings.from_global_paths(paths)
    standalones_builder = StandalonesBuilder(settings, paths)
    standalones_builder.build()
