from pathlib import Path

from cyclopts import App

from ..models.scalars import PartName
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
    minimum_delay: int = 5,
    workdir: Path = Path(),
) -> None:
    """Compile on change.

    Args:
        parts: Restrict deck compilation to these parts
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        minimum_delay: Minimum number of seconds before recompiling
        workdir: Path to move into before running the command

    """
    from logging import getLogger

    from ..building.watching import watch as watching_watch
    from ..configuring.paths import Paths
    from ..running import run

    logger = getLogger(__name__)

    logger.info("Watching the shared, current and user directories")
    paths = Paths.from_defaults(workdir)
    watching_watch(
        minimum_delay,
        frozenset([paths.shared_dir, paths.current_dir, paths.user_config_dir]),
        frozenset([paths.shared_tikz_pdf_dir, paths.pdf_dir, paths.build_dir]),
        run,
        paths=paths,
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
        target_whitelist=parts,
    )


@watch.command()
def section(
    section: str,
    flavor: str,
    /,
    *,
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,  # noqa: A002
    minimum_delay: int = 5,
    workdir: Path = Path(),
) -> None:
    """Compile a specific FLAVOR of a given SECTION on change.

    Args:
        section: Section to compile
        flavor: Flavor of SECTION to compile
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        minimum_delay: Minimum number of seconds before recompiling
        workdir: Path to move into before running the command

    """
    from logging import getLogger
    from tempfile import TemporaryDirectory

    from typer import launch

    from .. import app_name
    from ..building.watching import watch as watching_watch
    from ..configuring.paths import GlobalPaths, Paths
    from ..running import run_section

    logger = getLogger(__name__)

    logger.info(f"Watching {section} ⋅ {flavor}, the shared and user directories")
    global_paths = GlobalPaths.from_defaults(workdir)
    with (
        TemporaryDirectory(prefix=f"{app_name}-") as build_dir,
        TemporaryDirectory(prefix=f"{app_name}-") as pdf_dir,
    ):
        logger.info(
            f"Output directory located at [link=file://{pdf_dir}]{pdf_dir}[/link]",
            extra={"markup": True},
        )
        paths = Paths.from_defaults(
            workdir,
            check_depth=False,
            build_dir=Path(build_dir),
            pdf_dir=Path(pdf_dir),
            company_config=global_paths.template_company_config,
            deck_config=global_paths.template_deck_config,
        )
        launch(str(pdf_dir))
        watching_watch(
            minimum_delay,
            frozenset([paths.shared_dir, paths.user_config_dir]),
            frozenset([paths.shared_tikz_pdf_dir, paths.pdf_dir, paths.build_dir]),
            run_section,
            section=section,
            flavor=flavor,
            paths=paths,
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
    minimum_delay: int = 5,
    workdir: Path = Path(),
) -> None:
    """Compile a file on change.

    Args:
        latex: File to compile on change. Its path should be specified relative to \
            shared/latex
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        minimum_delay: Minimum number of seconds before recompiling
        workdir: Path to move into before running the command

    """
    from logging import getLogger
    from tempfile import TemporaryDirectory

    from typer import launch

    from .. import app_name
    from ..building.watching import watch as watching_watch
    from ..configuring.paths import GlobalPaths, Paths
    from ..running import run_file

    logger = getLogger(__name__)

    logger.info(f"Watching {latex}, the shared and user directories")
    global_paths = GlobalPaths.from_defaults(workdir)
    with (
        TemporaryDirectory(prefix=f"{app_name}-") as build_dir,
        TemporaryDirectory(prefix=f"{app_name}-") as pdf_dir,
    ):
        logger.info(
            f"Output directory located at [link=file://{pdf_dir}]{pdf_dir}[/link]",
            extra={"markup": True},
        )
        paths = Paths.from_defaults(
            workdir,
            check_depth=False,
            build_dir=Path(build_dir),
            pdf_dir=Path(pdf_dir),
            company_config=global_paths.template_company_config,
            deck_config=global_paths.template_deck_config,
        )
        launch(str(pdf_dir))
        watching_watch(
            minimum_delay,
            frozenset([paths.shared_dir, paths.user_config_dir]),
            frozenset([paths.shared_tikz_pdf_dir, paths.pdf_dir, paths.build_dir]),
            run_file,
            latex=latex,
            paths=paths,
            build_handout=handout,
            build_presentation=presentation,
            build_print=print,
        )


@watch.command()
def standalones(*, minimum_delay: int = 5, workdir: Path = Path()) -> None:
    """Compile standalones on change.

    Args:
        minimum_delay: Minimum number of seconds before recompiling
        workdir: Path to move into before running the command

    """
    from ..building.watching import watch as watching_watch
    from ..configuring.paths import GlobalPaths
    from ..running import run_standalones

    global_paths = GlobalPaths.from_defaults(workdir)

    watching_watch(
        minimum_delay,
        frozenset([global_paths.tikz_dir, global_paths.plt_dir]),
        frozenset([global_paths.shared_tikz_pdf_dir, global_paths.shared_plt_pdf_dir]),
        run_standalones,
        workdir,
    )
