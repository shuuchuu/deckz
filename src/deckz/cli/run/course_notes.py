from pathlib import Path

from .._options import Langs, unique
from . import app


@app.command(name="course-notes")
def run_course_notes(
    *,
    langs: Langs = ("fr",),
    watch: bool = False,
    dry_run: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile the course notes of the deck in WORKDIR (default).

    The deck's written-out reference: its parts and sections, each content
    file replaced by its chapter (`paths.course_notes_dir`, see `deckz show
    course-notes`), compiled through `paths.jinja2_course_notes_main_template`
    into `paths.course_notes_pdf_dir` (`pdf/course-notes/` by default). The
    files with no chapter written yet are listed, and left out.

    Args:
        langs: Languages to compile, each to its own output paths
            (English under an `en/` subdirectory), from each language's chapters
        watch: Recompile on file changes, instead of compiling once
        dry_run: Only print the outputs that would be compiled and the chapters
            each would re-render, without building anything
        workdir: Path to move into before running the command

    """
    from logging import getLogger

    from ...configuring.settings import DeckSettings
    from ...models import lang_dir
    from ...pipelines import COURSE_NOTES, build, course_notes_targets
    from ...pipelines import run_course_notes as _run_course_notes
    from .._presentation import (
        RichProgress,
        announce_build,
        print_plan_of,
        warn_missing_chapters,
    )

    logger = getLogger(__name__)
    settings = DeckSettings.from_yaml(workdir)
    paths = settings.paths
    langs = unique(langs)
    announce_build(
        str(paths.current_dir.relative_to(paths.git_dir)), langs, COURSE_NOTES
    )
    warn_missing_chapters(settings, langs)

    if dry_run:
        print_plan_of(course_notes_targets(settings, langs), COURSE_NOTES)
        return

    if not watch:
        build(course_notes_targets(settings, langs), COURSE_NOTES, RichProgress())
        for lang in langs:
            logger.info(
                "Course notes in %s",
                lang_dir(paths.course_notes_pdf_dir, lang).relative_to(paths.git_dir),
            )
        return

    from ...pipelines import watch as _watch

    logger.info("Watching the course notes, content, assets and current directories")
    to_watch = [
        paths.course_notes_dir,
        paths.content_dir,
        paths.assets_dir,
        paths.current_dir,
    ]
    _watch(
        frozenset(d for d in to_watch if d.is_dir()),
        frozenset([paths.pdf_dir, paths.html_dir, paths.build_dir]),
        _run_course_notes,
        settings=settings,
        langs=langs,
        progress=RichProgress(),
    )
