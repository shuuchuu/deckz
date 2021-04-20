from logging import getLogger
from pathlib import Path
from tempfile import TemporaryDirectory

from deckz import app_name
from deckz.cli import app
from deckz.paths import GlobalPaths, Paths
from deckz.watching import watch_file as watching_watch_file


_logger = getLogger(__name__)


@app.command()
def watch_file(
    latex: str,
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,
    minimum_delay: int = 5,
    workdir: Path = Path("."),
) -> None:
    """Compile on change."""
    _logger.info(f"Watching {latex}")
    global_paths = GlobalPaths.from_defaults(workdir)
    with TemporaryDirectory(prefix=f"{app_name}-") as build_dir, TemporaryDirectory(
        prefix=f"{app_name}-"
    ) as pdf_dir:
        _logger.info(
            f"Output directory located at [link=file://{pdf_dir}]{pdf_dir}[/link]",
            extra=dict(markup=True),
        )
        watching_watch_file(
            minimum_delay=minimum_delay,
            latex=latex,
            paths=Paths.from_defaults(
                workdir,
                check_depth=False,
                build_dir=Path(build_dir),
                pdf_dir=Path(pdf_dir),
                company_config=global_paths.template_company_config,
                deck_config=global_paths.template_deck_config,
            ),
            build_handout=handout,
            build_presentation=presentation,
            build_print=print,
        )
