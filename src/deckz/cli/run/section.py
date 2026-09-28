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
    watch: bool = False,
    open: bool = True,  # ruff: ignore[builtin-argument-shadowing]
    dry_run: bool = False,
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
        watch: Recompile on file changes, instead of compiling once
        open: Open the output directory once compiled. Disable for \
            agentic/headless use, where only the printed path is useful
        dry_run: Only print the PDFs that would be compiled and the content \
            fragments each would re-render, without building anything
        workdir: Path to move into before running the command

    """
    from logging import getLogger

    from ...checking import preview_settings
    from ...configuring.settings import DeckSettings
    from ...pipelines import OutputKinds, build, section_targets
    from ...pipelines import run_section as _run_section
    from .._presentation import RichProgress, open_path, print_plan_of

    logger = getLogger(__name__)
    settings = preview_settings(
        DeckSettings.from_yaml(workdir), "section", section, flavor
    )
    lang = "en" if en else "fr"
    outputs = OutputKinds(handout=handout, presentation=presentation, print=print)

    if dry_run:
        print_plan_of(section_targets(section, flavor, settings, lang), lang, outputs)
        return

    if watch:
        from ...pipelines import watch as _watch

        logger.info("Watching the content, assets, current and user directories")
        logger.info(
            f"Output directory located at [link=file://{settings.paths.pdf_dir}]"
            f"{settings.paths.pdf_dir}[/link]",
            extra={"markup": True},
        )
        if open:
            open_path(settings.paths.pdf_dir)
        to_watch = [
            settings.paths.content_dir,
            settings.paths.assets_dir,
            settings.paths.current_dir,
        ]
        if settings.paths.user_config_dir.exists():
            to_watch.append(settings.paths.user_config_dir)
        _watch(
            frozenset(to_watch),
            frozenset([settings.paths.pdf_dir, settings.paths.build_dir]),
            _run_section,
            section=section,
            flavor=flavor,
            settings=settings,
            lang=lang,
            outputs=outputs,
            progress=RichProgress(),
        )
        return

    build(
        section_targets(section, flavor, settings, lang),
        lang,
        outputs,
        RichProgress(),
    )
    logger.info(
        f"Output directory located at [link=file://{settings.paths.pdf_dir}]"
        f"{settings.paths.pdf_dir}[/link]",
        extra={"markup": True},
    )
    if open:
        open_path(settings.paths.pdf_dir)
