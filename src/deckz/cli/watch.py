from pathlib import Path

from cyclopts import App

from ..models import FlavorName, PartName
from . import app

watch = App(name="watch", help="Recompile on file changes.")
app.command(watch)


@watch.command()
def deck(
    parts: list[PartName] | None = None,
    /,
    *,
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    en: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile on change.

    Args:
        parts: Restrict deck compilation to these parts
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        en: Compile the English variant
        workdir: Path to move into before running the command

    """
    from logging import getLogger

    from ..configuring.settings import DeckSettings
    from ..pipelines import run, watch

    logger = getLogger(__name__)

    logger.info("Watching the latex, assets, current and user directories")
    settings = DeckSettings.from_yaml(workdir)
    to_watch = [
        settings.paths.latex_dir,
        settings.paths.assets_dir,
        settings.paths.current_dir,
    ]
    if settings.paths.user_config_dir.exists():
        to_watch.append(settings.paths.user_config_dir)
    watch(
        frozenset(to_watch),
        frozenset([settings.paths.pdf_dir, settings.paths.build_dir]),
        run,
        settings=settings,
        lang="en" if en else "fr",
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
        parts_whitelist=parts,
    )


@watch.command()
def section(
    section: str,
    flavor: FlavorName,
    /,
    *,
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    en: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile a specific FLAVOR of a given SECTION on change.

    Args:
        section: Section to compile
        flavor: Flavor of SECTION to compile
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        en: Compile the English variant
        workdir: Path to move into before running the command

    """
    from logging import getLogger
    from tempfile import TemporaryDirectory

    from typer import launch

    from .. import app_name
    from ..configuring.settings import DeckSettings
    from ..pipelines import run_section, watch

    logger = getLogger(__name__)

    logger.info("Watching the latex, assets, current and user directories")
    with (
        TemporaryDirectory(prefix=f"{app_name}-") as build_dir,
        TemporaryDirectory(prefix=f"{app_name}-") as pdf_dir,
    ):
        logger.info(
            f"Output directory located at [link=file://{pdf_dir}]{pdf_dir}[/link]",
            extra={"markup": True},
        )
        settings = DeckSettings.from_yaml(workdir)
        settings.paths.build_dir = Path(build_dir)
        settings.paths.pdf_dir = Path(pdf_dir)

        launch(str(pdf_dir))

        to_watch = [
            settings.paths.latex_dir,
            settings.paths.assets_dir,
            settings.paths.current_dir,
        ]
        if settings.paths.user_config_dir.exists():
            to_watch.append(settings.paths.user_config_dir)
        watch(
            frozenset(to_watch),
            frozenset([settings.paths.pdf_dir, settings.paths.build_dir]),
            run_section,
            section=section,
            flavor=flavor,
            settings=settings,
            lang="en" if en else "fr",
            build_handout=handout,
            build_presentation=presentation,
            build_print=print,
        )


@watch.command()
def file(
    latex: str,
    /,
    *,
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    en: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile a file on change.

    Args:
        latex: File to compile on change. Its path should be specified relative to \
            latex/
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        en: Compile the English variant
        workdir: Path to move into before running the command

    """
    from logging import getLogger
    from tempfile import TemporaryDirectory

    from typer import launch

    from .. import app_name
    from ..configuring.settings import DeckSettings
    from ..pipelines import run_file, watch

    logger = getLogger(__name__)

    logger.info(f"Watching {latex}, the latex, assets and user directories")
    with (
        TemporaryDirectory(prefix=f"{app_name}-") as build_dir,
        TemporaryDirectory(prefix=f"{app_name}-") as pdf_dir,
    ):
        logger.info(
            f"Output directory located at [link=file://{pdf_dir}]{pdf_dir}[/link]",
            extra={"markup": True},
        )
        settings = DeckSettings.from_yaml(workdir)
        settings.paths.build_dir = Path(build_dir)
        settings.paths.pdf_dir = Path(pdf_dir)
        launch(str(pdf_dir))
        to_watch = [settings.paths.latex_dir, settings.paths.assets_dir]
        if settings.paths.user_config_dir.exists():
            to_watch.append(settings.paths.user_config_dir)
        watch(
            frozenset(to_watch),
            frozenset([settings.paths.pdf_dir, settings.paths.build_dir]),
            run_file,
            latex=latex,
            settings=settings,
            lang="en" if en else "fr",
            build_handout=handout,
            build_presentation=presentation,
            build_print=print,
        )


@watch.command()
def assets(*, workdir: Path = Path()) -> None:
    """Compile assets on change.

    Args:
        workdir: Path to move into before running the command

    """
    from ..components.factory import GlobalSettingsFactory
    from ..configuring.settings import GlobalSettings
    from ..pipelines import run_assets, watch

    settings = GlobalSettings.from_yaml(workdir)
    assets_builder = GlobalSettingsFactory(settings).assets_builder()

    watch(
        frozenset(assets_builder.watched_dirs()),
        frozenset([settings.paths.assets_dir]),
        run_assets,
        workdir,
    )
