from pathlib import Path

from ...models import FlavorName
from . import app


@app.command(name="section")
def run_section(
    section: str,
    flavor: FlavorName,
    /,
    *,
    handout: bool = True,
    presentation: bool = True,
    print: bool = True,  # ruff: ignore[builtin-argument-shadowing]
    en: bool = False,
    open: bool = True,  # ruff: ignore[builtin-argument-shadowing]
    workdir: Path = Path(),
) -> None:
    """Compile a specific FLAVOR of a given SECTION.

    Output is written to a dedicated scratch directory under \
    `<git_dir>/.run/section/`, not the current deck's own build/pdf \
    directories, so repeated previews don't clutter a real deck's output.

    Args:
        section: Section to compile
        flavor: Flavor of SECTION to compile
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        en: Compile the English variant
        open: Open the output directory once compiled. Disable for \
            agentic/headless use, where only the printed path is useful
        workdir: Path to move into before running the command

    """
    from logging import getLogger

    from typer import launch

    from ...configuring.settings import DeckSettings
    from ...pipelines import run_section

    logger = getLogger(__name__)
    settings = DeckSettings.from_yaml(workdir)
    scratch_dir = settings.paths.git_dir / ".run" / "section" / section / flavor
    settings.paths.build_dir = scratch_dir / ".build"
    settings.paths.pdf_dir = scratch_dir / "pdf"

    run_section(
        section=section,
        flavor=flavor,
        settings=settings,
        lang="en" if en else "fr",
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
    )
    logger.info(
        f"Output directory located at [link=file://{settings.paths.pdf_dir}]"
        f"{settings.paths.pdf_dir}[/link]",
        extra={"markup": True},
    )
    if open:
        launch(str(settings.paths.pdf_dir))
