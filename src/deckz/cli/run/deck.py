from pathlib import Path

from ...models import PartName
from .._options import Langs, unique
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
    part_handouts: bool = True,
    sync: bool = True,
    langs: Langs = ("fr",),
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
        dry_run: Only print the outputs that would be compiled and the content
            fragments each would re-render (new or changed since its last
            build), without building anything, assets included
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import DeckSettings
    from ...pipelines import OutputKinds, build, deck_targets
    from ...pipelines import run as _run
    from .._presentation import RichProgress, announce_build, print_plan_of

    settings = DeckSettings.from_yaml(workdir)
    langs = unique(langs)
    outputs = OutputKinds(
        handout=handout,
        presentation=presentation,
        print=print,
        html=html,
        part_handouts=part_handouts,
        sync=sync,
    )
    announce_build(
        str(settings.paths.current_dir.relative_to(settings.paths.git_dir)),
        langs,
        outputs,
    )

    if dry_run:
        print_plan_of(deck_targets(settings, langs, parts), outputs)
        return

    if not watch:
        build(deck_targets(settings, langs, parts), outputs, RichProgress())
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
        langs=langs,
        outputs=outputs,
        parts=parts,
        progress=RichProgress(),
    )
