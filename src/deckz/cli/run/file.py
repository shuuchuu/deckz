from pathlib import Path

from . import app


@app.command(name="file")
def run_file(
    path: str,
    /,
    *,
    handout: bool = True,
    presentation: bool = True,
    print: bool = True,  # ruff: ignore[builtin-argument-shadowing]
    en: bool = False,
    watch: bool = False,
    open: bool = True,  # ruff: ignore[builtin-argument-shadowing]
    dry_run: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile a single content file.

    Output is written to a dedicated scratch directory under
    `<git_dir>/.run/file/`, not the current deck's own build/pdf
    directories, so repeated previews don't clutter a real deck's output.

    Args:
        path: File to compile, relative to content/ and without its
            extension
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        en: Compile the English variant
        watch: Recompile on file changes, instead of compiling once
        open: Open the output directory once compiled. Disable for
            agentic/headless use, where only the printed path is useful
        dry_run: Only print the PDFs that would be compiled and the content
            fragments each would re-render, without building anything
        workdir: Path to move into before running the command

    """
    from logging import getLogger

    from ...checking import preview_settings
    from ...configuring.settings import DeckSettings
    from ...pipelines import OutputKinds, build, file_targets
    from ...pipelines import run_file as _run_file
    from .._presentation import RichProgress, open_path, print_plan_of

    logger = getLogger(__name__)
    settings = preview_settings(DeckSettings.from_yaml(workdir), "file", path)
    lang = "en" if en else "fr"
    outputs = OutputKinds(handout=handout, presentation=presentation, print=print)

    if dry_run:
        print_plan_of(file_targets(path, settings, lang), lang, outputs)
        return

    if watch:
        from ...pipelines import watch as _watch

        logger.info(f"Watching {path}, the content, assets and user directories")
        logger.info(
            f"Output directory located at [link=file://{settings.paths.pdf_dir}]"
            f"{settings.paths.pdf_dir}[/link]",
            extra={"markup": True},
        )
        if open:
            open_path(settings.paths.pdf_dir)
        to_watch = [settings.paths.content_dir, settings.paths.assets_dir]
        if settings.paths.user_config_dir.exists():
            to_watch.append(settings.paths.user_config_dir)
        _watch(
            frozenset(to_watch),
            frozenset([settings.paths.pdf_dir, settings.paths.build_dir]),
            _run_file,
            path=path,
            settings=settings,
            lang=lang,
            outputs=outputs,
            progress=RichProgress(),
        )
        return

    build(file_targets(path, settings, lang), lang, outputs, RichProgress())
    logger.info(
        f"Output directory located at [link=file://{settings.paths.pdf_dir}]"
        f"{settings.paths.pdf_dir}[/link]",
        extra={"markup": True},
    )
    if open:
        open_path(settings.paths.pdf_dir)
