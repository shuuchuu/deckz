from logging import getLogger
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

from typer import Argument, Option, Typer, launch

from deckz import app_name
from deckz.cli import app
from deckz.paths import GlobalPaths, Paths
from deckz.running import run, run_file, run_section, run_standalones
from deckz.watching import watch

_logger = getLogger(__name__)


app_watch = Typer(help="Compile on change")
app.add_typer(app_watch, name="watch")


@app_watch.command()
def deck(
    targets: Optional[List[str]] = Argument(None, help="Targets to watch"),
    handout: bool = Option(False, help="Produce PDFs without animations"),
    presentation: bool = Option(True, help="Produce PDFs with animations"),
    print: bool = Option(False, help="Produce a printable PDF"),
    minimum_delay: int = Option(5, help="Minimum number of seconds before recompiling"),
    workdir: Path = Option(
        Path("."), help="Path to move into before running the command"
    ),
) -> None:
    """Compile on change."""
    _logger.info("Watching the shared, current and user directories")
    paths = Paths.from_defaults(workdir)
    watch(
        minimum_delay,
        frozenset([paths.shared_dir, paths.current_dir, paths.user_config_dir]),
        frozenset([paths.shared_tikz_pdf_dir, paths.pdf_dir, paths.build_dir]),
        run,
        paths=paths,
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
        target_whitelist=targets,
    )


@app_watch.command()
def section(
    section: str = Argument(..., help="Section to watch"),
    flavor: str = Argument(..., help="Flavor of the section to watch"),
    handout: bool = Option(False, help="Produce PDFs without animations"),
    presentation: bool = Option(True, help="Produce PDFs with animations"),
    print: bool = Option(False, help="Produce a printable PDF"),
    minimum_delay: int = Option(5, help="Minimum number of seconds before recompiling"),
    workdir: Path = Option(
        Path("."), help="Path to move into before running the command"
    ),
) -> None:
    """Compile a specific section on change."""
    _logger.info(f"Watching {section} ⋅ {flavor}, the shared and user directories")
    global_paths = GlobalPaths.from_defaults(workdir)
    with TemporaryDirectory(prefix=f"{app_name}-") as build_dir, TemporaryDirectory(
        prefix=f"{app_name}-"
    ) as pdf_dir:
        _logger.info(
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
        watch(
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


@app_watch.command()
def file(
    latex: str = Argument(..., help="File to watch, relative to share/latex"),
    handout: bool = Option(False, help="Produce PDFs without animations"),
    presentation: bool = Option(True, help="Produce PDFs with animations"),
    print: bool = Option(False, help="Produce a printable PDF"),
    minimum_delay: int = Option(5, help="Minimum number of seconds before recompiling"),
    workdir: Path = Option(
        Path("."), help="Path to move into before running the command"
    ),
) -> None:
    """Compile a specific file on change."""
    _logger.info(f"Watching {latex}, the shared and user directories")
    global_paths = GlobalPaths.from_defaults(workdir)
    with TemporaryDirectory(prefix=f"{app_name}-") as build_dir, TemporaryDirectory(
        prefix=f"{app_name}-"
    ) as pdf_dir:
        _logger.info(
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
        watch(
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


@app_watch.command()
def standalones(
    minimum_delay: int = Option(5, help="Minimum number of seconds before recompiling"),
    workdir: Path = Option(
        Path("."), help="Path to move into before running the command"
    ),
) -> None:
    """Compile standalones on change."""
    global_paths = GlobalPaths.from_defaults(workdir)

    watch(
        minimum_delay,
        frozenset([global_paths.tikz_dir, global_paths.plt_dir]),
        frozenset([global_paths.shared_tikz_pdf_dir, global_paths.shared_plt_pdf_dir]),
        run_standalones,
        workdir,
    )
