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
    en: bool = False,
    watch: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile the deck in WORKDIR (default).

    Args:
        parts: Restrict deck compilation to these parts
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        en: Compile the English variant. Every resolved file, title and \
            variable must have a complete English translation, or the build \
            fails immediately
        watch: Recompile on file changes, instead of compiling once
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import DeckSettings
    from ...pipelines import run as _run

    settings = DeckSettings.from_yaml(workdir)

    if not watch:
        _run(
            settings=settings,
            lang="en" if en else "fr",
            build_handout=handout,
            build_presentation=presentation,
            build_print=print,
            parts_whitelist=parts,
        )
        return

    from logging import getLogger

    from ...pipelines import watch as _watch

    logger = getLogger(__name__)
    logger.info("Watching the latex, assets, current and user directories")
    to_watch = [
        settings.paths.latex_dir,
        settings.paths.assets_dir,
        settings.paths.current_dir,
    ]
    if settings.paths.user_config_dir.exists():
        to_watch.append(settings.paths.user_config_dir)
    _watch(
        frozenset(to_watch),
        frozenset([settings.paths.pdf_dir, settings.paths.build_dir]),
        _run,
        settings=settings,
        lang="en" if en else "fr",
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
        parts_whitelist=parts,
    )
