from pathlib import Path

from cyclopts import App

from ..models import FlavorName, PartName
from . import app

watch = App(name="watch")
app.command(watch)


@watch.command()
def deck(
    parts: list[PartName] | None = None,
    /,
    *,
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,  # noqa: A002
    workdir: Path = Path(),
) -> None:
    """Compile on change.

    Args:
        parts: Restrict deck compilation to these parts
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        workdir: Path to move into before running the command

    """
    from logging import getLogger

    from ..configuring.settings import DeckSettings
    from ..pipelines import run, watch

    logger = getLogger(__name__)

    logger.info("Watching the shared, current and user directories")
    settings = DeckSettings.from_yaml(workdir)
    to_watch = [settings.paths.shared_dir, settings.paths.current_dir]
    if settings.paths.user_config_dir.exists():
        to_watch.append(settings.paths.user_config_dir)
    watch(
        frozenset(to_watch),
        frozenset(
            [
                settings.paths.shared_tikz_pdf_dir,
                settings.paths.pdf_dir,
                settings.paths.build_dir,
            ]
        ),
        run,
        settings=settings,
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
    print: bool = False,  # noqa: A002
    workdir: Path = Path(),
) -> None:
    """Compile a specific FLAVOR of a given SECTION on change.

    Args:
        section: Section to compile
        flavor: Flavor of SECTION to compile
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        workdir: Path to move into before running the command

    """
    from logging import getLogger
    from tempfile import TemporaryDirectory

    from typer import launch

    from .. import app_name
    from ..configuring.settings import DeckSettings
    from ..pipelines import run_section, watch

    logger = getLogger(__name__)

    logger.info("Watching the shared, current and user directories")
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

        to_watch = [settings.paths.shared_dir, settings.paths.current_dir]
        if settings.paths.user_config_dir.exists():
            to_watch.append(settings.paths.user_config_dir)
        watch(
            frozenset(to_watch),
            frozenset(
                [
                    settings.paths.shared_tikz_pdf_dir,
                    settings.paths.pdf_dir,
                    settings.paths.build_dir,
                ]
            ),
            run_section,
            section=section,
            flavor=flavor,
            settings=settings,
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
    print: bool = False,  # noqa: A002
    workdir: Path = Path(),
) -> None:
    """Compile a file on change.

    Args:
        latex: File to compile on change. Its path should be specified relative to \
            shared/latex
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        workdir: Path to move into before running the command

    """
    from logging import getLogger
    from tempfile import TemporaryDirectory

    from typer import launch

    from .. import app_name
    from ..configuring.settings import DeckSettings
    from ..pipelines import run_file, watch

    logger = getLogger(__name__)

    logger.info(f"Watching {latex}, the shared and user directories")
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
        to_watch = [settings.paths.shared_dir]
        if settings.paths.user_config_dir.exists():
            to_watch.append(settings.paths.user_config_dir)
        watch(
            frozenset(to_watch),
            frozenset(
                [
                    settings.paths.shared_tikz_pdf_dir,
                    settings.paths.pdf_dir,
                    settings.paths.build_dir,
                ]
            ),
            run_file,
            latex=latex,
            settings=settings,
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
    from ..configuring.settings import GlobalSettings
    from ..pipelines import run_assets, watch

    settings = GlobalSettings.from_yaml(workdir)

    watch(
        frozenset(
            [settings.paths.tikz_dir, settings.paths.plt_dir, settings.paths.plotly_dir]
        ),
        frozenset(
            [
                settings.paths.shared_tikz_pdf_dir,
                settings.paths.shared_plt_pdf_dir,
                settings.paths.shared_plotly_pdf_dir,
            ]
        ),
        run_assets,
        workdir,
    )
