from pathlib import Path

from ...models import PartName
from . import app


@app.command(name="deck")
@app.default
def run(
    *,
    parts: list[PartName] | None = None,
    handout: bool = True,
    presentation: bool = True,
    print: bool = True,  # ruff: ignore[builtin-argument-shadowing]
    html: bool = False,
    en: bool = False,
    watch: bool = False,
    dry_run: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile the deck in WORKDIR (default).

    Args:
        parts: Restrict deck compilation to these parts
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        html: Produce an HTML deck (whole deck, with a table of contents)
        en: Compile the English variant. Every resolved file, title and
            variable must have a complete English translation, or the build
            fails immediately
        watch: Recompile on file changes, instead of compiling once
        dry_run: Only print the outputs that would be compiled and the content
            fragments each would re-render (new or changed since its last
            build), without building anything, assets included
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import DeckSettings
    from ...pipelines import OutputKinds, build, deck_targets
    from ...pipelines import run as _run
    from .._presentation import RichProgress, print_plan_of

    settings = DeckSettings.from_yaml(workdir)
    lang = "en" if en else "fr"
    outputs = OutputKinds(
        handout=handout, presentation=presentation, print=print, html=html
    )

    if dry_run:
        print_plan_of(deck_targets(settings, lang, parts), lang, outputs)
        return

    if not watch:
        build(deck_targets(settings, lang, parts), lang, outputs, RichProgress())
        return

    from logging import getLogger

    from ...pipelines import watch as _watch

    logger = getLogger(__name__)
    logger.info("Watching the content, assets, current and user directories")
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
        _run,
        settings=settings,
        lang=lang,
        outputs=outputs,
        parts=parts,
        progress=RichProgress(),
    )
