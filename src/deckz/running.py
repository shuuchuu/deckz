from collections.abc import Iterable
from pathlib import Path
from sys import stderr

from rich import print as rich_print
from rich.progress import BarColumn, Progress

from .building.building import Builder
from .building.standalones import StandalonesBuilder
from .configuring.settings import DeckSettings, GlobalSettings
from .configuring.variables import get_variables
from .exceptions import DeckzError
from .models.deck import Deck
from .models.scalars import FlavorName, PartName
from .processing.part_dependencies import PartDependenciesProcessor
from .processing.rich_tree import RichTreeProcessor
from .processing.titles_and_contents import SlidesProcessor
from .utils import all_deck_settings


def _build(
    deck: Deck,
    settings: DeckSettings,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> bool:
    variables = get_variables(settings)
    tree = RichTreeProcessor().process(deck)
    if tree is not None:
        rich_print(tree, file=stderr)
        msg = "deck parsing failed"
        raise DeckzError(msg)
    dependencies = PartDependenciesProcessor().process(deck)
    parts_slides = SlidesProcessor(
        settings.paths.shared_dir, settings.paths.current_dir
    ).process(deck)
    StandalonesBuilder(settings).build()
    return Builder(
        variables=variables,
        settings=settings,
        deck_name=deck.name,
        parts_slides=parts_slides,
        dependencies=dependencies,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    ).build()


def run(
    settings: DeckSettings,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    parts_whitelist: Iterable[PartName] | None = None,
) -> None:
    parser_config = settings.components.parser_config
    deck = parser_config.get_model_class()(
        settings.paths.local_latex_dir, settings.paths.shared_latex_dir, parser_config
    ).from_deck_definition(settings.paths.deck_definition)
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
    parser_config = settings.components.parser_config
    deck = parser_config.get_model_class()(
        settings.paths.local_latex_dir, settings.paths.shared_latex_dir, parser_config
    ).from_file(latex)
    _build(
        deck=deck,
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
    parser_config = settings.components.parser_config
    deck = parser_config.get_model_class()(
        settings.paths.local_latex_dir, settings.paths.shared_latex_dir, parser_config
    ).from_section(section, flavor)
    _build(
        deck=deck,
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
    StandalonesBuilder(global_settings).build()
    decks_settings = list(all_deck_settings(global_settings.paths.git_dir))
    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
    ) as progress:
        task_id = progress.add_task("Building decks…", total=len(decks_settings))
        for deck_settings in decks_settings:
            parser_config = deck_settings.components.parser_config
            deck = parser_config.get_model_class()(
                deck_settings.paths.local_latex_dir,
                deck_settings.paths.shared_latex_dir,
                parser_config,
            ).from_deck_definition(deck_settings.paths.deck_definition)
            result = _build(
                deck=deck,
                settings=deck_settings,
                build_handout=build_handout,
                build_presentation=build_presentation,
                build_print=build_print,
            )
            if not result:
                break
            progress.update(task_id, advance=1)


def run_standalones(directory: Path) -> None:
    """Build all the project standalones (images, tikz, plots, etc).

    Args:
        directory: Path to the current directory. Will be used to find the project \
            directory
    """
    settings = GlobalSettings.from_yaml(directory)
    standalones_builder = StandalonesBuilder(settings)
    standalones_builder.build()
