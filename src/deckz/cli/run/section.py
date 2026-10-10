from pathlib import Path

from ...models import FlavorName
from .._options import Langs, unique
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
    html: bool = False,
    part_handouts: bool = True,
    sync: bool = True,
    langs: Langs = ("fr",),
    watch: bool = False,
    open: bool = True,  # ruff: ignore[builtin-argument-shadowing]
    dry_run: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile a specific FLAVOR of a given SECTION.

    Output is written to a dedicated scratch directory under
    `<git_dir>/.run/section/`, not the current deck's own build/pdf
    directories, so repeated previews don't clutter a real deck's output.

    Args:
        section: Section to compile
        flavor: Flavor of SECTION to compile
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        html: Produce an HTML deck (whole deck, with a table of contents)
        part_handouts: With --handout, also produce one handout per part,
            besides the whole deck's
        sync: Once everything compiled, remove the PDFs that no build of
            the deck produces anymore (a removed or renamed part, a renamed
            deck, a stray file), in the languages this run built. What
            this run merely skips (another language, presentations after
            --no-presentation, other parts with --parts) is kept
        langs: Languages to compile, each to its own output paths
            (English under an `en/` subdirectory). English is strict: every
            resolved file, title and variable must have a complete English
            translation, or the build fails before compiling anything
        watch: Recompile on file changes, instead of compiling once
        open: Open the output directory once compiled. Disable for
            agentic/headless use, where only the printed path is useful
        dry_run: Only print the outputs that would be compiled and the content
            fragments each would re-render, without building anything
        workdir: Path to move into before running the command

    """
    from logging import getLogger

    from ...checking import preview_settings
    from ...configuring.settings import DeckSettings
    from ...pipelines import OutputKinds, build, section_targets
    from ...pipelines import run_section as _run_section
    from .._presentation import (
        RichProgress,
        announce_build,
        print_plan_of,
        show_output_dirs,
    )

    logger = getLogger(__name__)
    settings = preview_settings(
        DeckSettings.from_yaml(workdir), "section", section, flavor
    )
    langs = unique(langs)
    outputs = OutputKinds(
        handout=handout,
        presentation=presentation,
        print=print,
        html=html,
        part_handouts=part_handouts,
        sync=sync,
    )
    announce_build(f"{section}@{flavor}", langs, outputs)

    if dry_run:
        print_plan_of(section_targets(section, flavor, settings, langs), outputs)
        return

    if watch:
        from ...pipelines import watch as _watch

        logger.info("Watching the content, assets, current and user directories")
        show_output_dirs(settings, langs, outputs, open_dir=open)
        to_watch = [
            settings.paths.content_dir,
            settings.paths.assets_dir,
            settings.paths.current_dir,
        ]
        if settings.paths.user_config_dir.exists():
            to_watch.append(settings.paths.user_config_dir)
        _watch(
            frozenset(to_watch),
            frozenset(
                [
                    settings.paths.pdf_dir,
                    settings.paths.html_dir,
                    settings.paths.build_dir,
                ]
            ),
            _run_section,
            section=section,
            flavor=flavor,
            settings=settings,
            langs=langs,
            outputs=outputs,
            progress=RichProgress(),
        )
        return

    build(section_targets(section, flavor, settings, langs), outputs, RichProgress())
    show_output_dirs(settings, langs, outputs, open_dir=open)
