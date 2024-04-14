from pathlib import Path

from typer import Typer
from typing_extensions import Annotated

from . import HandoutOption, Option, PresentationOption, PrintOption, WorkdirOption, app

_MinimumDelayOption = Option(help="Minimum number of seconds before recompiling")


watch = Typer()
app.add_typer(watch, name="watch")


@watch.command()
def deck(
    targets: list[str],
    handout: Annotated[bool, HandoutOption] = False,
    presentation: Annotated[bool, PresentationOption] = True,
    print: Annotated[bool, PrintOption] = False,
    minimum_delay: Annotated[int, _MinimumDelayOption] = 5,
    workdir: Annotated[Path, WorkdirOption] = Path("."),
) -> None:
    """
    Compile on change.

    Watching can be restricted to given TARGETS.
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
        target_whitelist=targets or None,
    )


@watch.command()
def section(
    section: str,
    flavor: str,
    handout: Annotated[bool, HandoutOption] = False,
    presentation: Annotated[bool, PresentationOption] = True,
    print: Annotated[bool, PrintOption] = False,
    minimum_delay: Annotated[int, _MinimumDelayOption] = 5,
    workdir: Annotated[Path, WorkdirOption] = Path("."),
) -> None:
    """Compile a specific FLAVOR of a given SECTION on change."""
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
    with TemporaryDirectory(prefix=f"{app_name}-") as build_dir, TemporaryDirectory(
        prefix=f"{app_name}-"
    ) as pdf_dir:
        logger.info(
            f"Output directory located at [link=file://{pdf_dir}]{pdf_dir}[/link]",
            extra=dict(markup=True),
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
    handout: Annotated[bool, HandoutOption] = False,
    presentation: Annotated[bool, PresentationOption] = True,
    print: Annotated[bool, PrintOption] = False,
    minimum_delay: Annotated[int, _MinimumDelayOption] = 5,
    workdir: Annotated[Path, WorkdirOption] = Path("."),
) -> None:
    """Compile FILE on change, specified relative to share/latex."""
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
    with TemporaryDirectory(prefix=f"{app_name}-") as build_dir, TemporaryDirectory(
        prefix=f"{app_name}-"
    ) as pdf_dir:
        logger.info(
            f"Output directory located at [link=file://{pdf_dir}]{pdf_dir}[/link]",
            extra=dict(markup=True),
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
def standalones(
    minimum_delay: Annotated[int, _MinimumDelayOption] = 5,
    workdir: Annotated[Path, WorkdirOption] = Path("."),
) -> None:
    """Compile standalones on change."""
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
