from pathlib import Path

from . import app


@app.command(name="file")
def run_file(
    latex: str,
    /,
    *,
    handout: bool = True,
    presentation: bool = True,
    print: bool = True,  # ruff: ignore[builtin-argument-shadowing]
    en: bool = False,
    watch: bool = False,
    open: bool = True,  # ruff: ignore[builtin-argument-shadowing]
    workdir: Path = Path(),
) -> None:
    """Compile a single LaTeX file.

    Output is written to a dedicated scratch directory under \
    `<git_dir>/.run/file/`, not the current deck's own build/pdf \
    directories, so repeated previews don't clutter a real deck's output.

    Args:
        latex: File to compile. Its path should be specified relative to \
            latex/
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        en: Compile the English variant
        watch: Recompile on file changes, instead of compiling once
        open: Open the output directory once compiled. Disable for \
            agentic/headless use, where only the printed path is useful
        workdir: Path to move into before running the command

    """
    from logging import getLogger

    from typer import launch

    from ...configuring.settings import DeckSettings
    from ...pipelines import run_file as _run_file

    logger = getLogger(__name__)
    settings = DeckSettings.from_yaml(workdir)
    scratch_dir = settings.paths.git_dir / ".run" / "file" / latex
    settings.paths.build_dir = scratch_dir / ".build"
    settings.paths.pdf_dir = scratch_dir / "pdf"

    if watch:
        from ...pipelines import watch as _watch

        logger.info(f"Watching {latex}, the latex, assets and user directories")
        logger.info(
            f"Output directory located at [link=file://{settings.paths.pdf_dir}]"
            f"{settings.paths.pdf_dir}[/link]",
            extra={"markup": True},
        )
        if open:
            launch(str(settings.paths.pdf_dir))
        to_watch = [settings.paths.latex_dir, settings.paths.assets_dir]
        if settings.paths.user_config_dir.exists():
            to_watch.append(settings.paths.user_config_dir)
        _watch(
            frozenset(to_watch),
            frozenset([settings.paths.pdf_dir, settings.paths.build_dir]),
            _run_file,
            latex=latex,
            settings=settings,
            lang="en" if en else "fr",
            build_handout=handout,
            build_presentation=presentation,
            build_print=print,
        )
        return

    _run_file(
        latex=latex,
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
