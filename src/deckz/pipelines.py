from collections.abc import Callable, Iterable, Set
from logging import getLogger
from pathlib import Path
from typing import Any

from rich.progress import BarColumn, Progress
from watchfiles import watch as watchfiles_watch

from .checking import build_all_deck, build_shared_deck, check_scratch_dir
from .components.factory import DeckSettingsFactory, GlobalSettingsFactory
from .configuring.settings import DeckSettings, GlobalSettings
from .configuring.variables import get_variables, resolve_variables
from .models import Deck, FlavorName, Lang, PartName
from .utils import all_deck_settings

_logger = getLogger(__name__)


def _build(
    deck: Deck,
    settings: DeckSettings,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    basedirs: tuple[Path, ...] | None = None,
) -> bool:
    variables = {**get_variables(settings, lang=lang), "lang": lang}
    resolve_variables(deck, variables)
    factory = DeckSettingsFactory(settings, lang=lang)
    factory.assets_builder().build_assets()
    return factory.deck_builder(
        variables=variables,
        deck=deck,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
        basedirs=basedirs,
    ).build_deck()


def run(
    settings: DeckSettings,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    parts_whitelist: Iterable[PartName] | None = None,
) -> None:
    parser = DeckSettingsFactory(settings, lang=lang).parser()
    deck = parser.from_deck_definition(settings.paths.deck_definition)
    if parts_whitelist is not None:
        deck.filter(parts_whitelist)
    _build(
        deck=deck,
        settings=settings,
        lang=lang,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    )


def run_file(
    latex: str,
    settings: DeckSettings,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    _build(
        deck=DeckSettingsFactory(settings, lang=lang).parser().from_file(latex),
        settings=settings,
        lang=lang,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    )


def run_section(
    section: str,
    flavor: FlavorName,
    settings: DeckSettings,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    _build(
        deck=DeckSettingsFactory(settings, lang=lang)
        .parser()
        .from_section(section, flavor),
        settings=settings,
        lang=lang,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    )


def run_all(
    directory: Path,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    global_settings = GlobalSettings.from_yaml(directory)
    GlobalSettingsFactory(global_settings).assets_builder().build_assets()
    decks_settings = list(all_deck_settings(global_settings.paths.git_dir))
    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
    ) as progress:
        task_id = progress.add_task("Building decks…", total=len(decks_settings))
        for deck_settings in decks_settings:
            result = _build(
                deck=DeckSettingsFactory(deck_settings, lang=lang)
                .parser()
                .from_deck_definition(deck_settings.paths.deck_definition),
                settings=deck_settings,
                lang=lang,
                build_handout=build_handout,
                build_presentation=build_presentation,
                build_print=build_print,
            )
            if not result:
                break
            progress.update(task_id, advance=1)


def check_shared(
    directory: Path,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    global_settings = GlobalSettings.from_yaml(directory)
    git_dir = global_settings.paths.git_dir
    GlobalSettingsFactory(global_settings).assets_builder().build_assets()
    settings = DeckSettings.from_yaml(check_scratch_dir(git_dir, "shared"))
    deck = build_shared_deck(
        settings.paths.shared_latex_dir, settings.file_extensions, lang
    )
    _build(
        deck=deck,
        settings=settings,
        lang=lang,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
        basedirs=(git_dir,),
    )


def check_all(
    directory: Path,
    lang: Lang,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    global_settings = GlobalSettings.from_yaml(directory)
    git_dir = global_settings.paths.git_dir
    GlobalSettingsFactory(global_settings).assets_builder().build_assets()
    settings = DeckSettings.from_yaml(check_scratch_dir(git_dir, "all"))
    deck = build_all_deck(
        git_dir, settings.paths.shared_latex_dir, settings.file_extensions, lang
    )
    _build(
        deck=deck,
        settings=settings,
        lang=lang,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
        basedirs=(git_dir,),
    )


def run_assets(directory: Path) -> None:
    """Build all the project standalones (images, tikz, plots, etc).

    Args:
        directory: Path to the current directory. Will be used to find the project \
            directory
    """
    GlobalSettingsFactory(
        GlobalSettings.from_yaml(directory)
    ).assets_builder().build_assets()


def watch[**P](
    watch: Set[Path],
    avoid: Set[Path],
    function: Callable[P, Any],
    *function_args: P.args,
    **function_kwargs: P.kwargs,
) -> None:
    dirs_to_avoid = avoid | {
        p.resolve() for dir_to_avoid in avoid for p in dir_to_avoid.glob("**")
    }

    dirs_to_watch = watch | {
        r_to_watch
        for dir_to_watch in watch
        for p in dir_to_watch.glob("**")
        if (r_to_watch := p.resolve()) not in dirs_to_avoid
    }
    print("\n".join(sorted(str(d) for d in dirs_to_watch)))
    _logger.info("Initial build")
    try:
        function(*function_args, **function_kwargs)
        _logger.info("Initial build finished")
    except Exception as e:
        _logger.exception(str(e), extra={"markup": True})

    for _ in watchfiles_watch(*dirs_to_watch, raise_interrupt=False, recursive=False):
        _logger.info("Detected changes, starting a new build")
        try:
            function(*function_args, **function_kwargs)
            _logger.info("Build finished")
        except Exception as e:
            _logger.exception(str(e), extra={"markup": True})
