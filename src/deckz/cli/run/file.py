from pathlib import Path

from .._options import Langs, unique
from . import app


@app.command(name="file")
def run_file(
    path: str,
    /,
    *,
    handout: bool = True,
    presentation: bool = True,
    print: bool = True,  # ruff: ignore[builtin-argument-shadowing]
    html: bool = False,
    part_handouts: bool = True,
    sync: bool = True,
    course_notes: bool = False,
    langs: Langs = ("fr",),
    watch: bool = False,
    open: bool = True,  # ruff: ignore[builtin-argument-shadowing]
    dry_run: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile a single content file, or its course notes chapter.

    Output is written to a dedicated scratch directory under
    `<git_dir>/.run/file/`, not the current deck's own build/pdf
    directories, so repeated previews don't clutter a real deck's output.

    A course notes chapter's path (`course-notes/nn/intro.md`, or its `en/`
    version: `paths.course_notes_dir`) builds that chapter alone, as
    `--course-notes --no-handout --no-presentation --no-print` would: with
    the course notes' main template, whether a deck includes it or not.

    Args:
        path: File to compile, relative to content/ and without its
            extension (`nn/intro`), or as found from here or from the
            repository's root (`content/nn/intro.md`), or a course notes
            chapter (`course-notes/nn/intro.md`), in the languages --lang asks
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
        course_notes: Also compile the file's course notes chapter (as
            `deckz run course-notes` would, into the scratch directory's
            `pdf/course-notes/`), in the languages it is written in. With
            --no-handout --no-presentation --no-print, only it, and a
            language with no chapter fails
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
    from functools import partial
    from logging import getLogger

    from ...checking import chapter_relative, content_relative, preview_settings
    from ...configuring.settings import DeckSettings
    from ...pipelines import OutputKinds, build, chapters_required, file_targets
    from ...pipelines import run_file as _run_file
    from .._presentation import (
        RichProgress,
        announce_build,
        print_plan_of,
        show_output_dirs,
    )

    logger = getLogger(__name__)
    deck_settings = DeckSettings.from_yaml(workdir)
    chapter = chapter_relative(deck_settings, path)
    if chapter is not None:
        logger.info(f"{path} is the course notes chapter of {chapter}: building it")
    slides = chapter is None
    path = content_relative(deck_settings, path) if slides else chapter
    settings = preview_settings(deck_settings, "file", path)
    langs = unique(langs)
    outputs = OutputKinds(
        handout=slides and handout,
        presentation=slides and presentation,
        print=slides and print,
        html=slides and html,
        part_handouts=part_handouts,
        sync=sync,
        course_notes=course_notes or not slides,
    )
    announce_build(path, langs, outputs)

    targets = partial(
        file_targets,
        path,
        settings,
        langs,
        course_notes=outputs.course_notes,
        required=chapters_required(outputs),
    )

    if dry_run:
        print_plan_of(targets(), outputs)
        return

    if watch:
        from ...pipelines import watch as _watch

        logger.info(f"Watching {path}, the content, assets and user directories")
        show_output_dirs(settings, langs, outputs, open_dir=open)
        to_watch = [settings.paths.content_dir, settings.paths.assets_dir]
        if outputs.course_notes and settings.paths.course_notes_dir.is_dir():
            to_watch.append(settings.paths.course_notes_dir)
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
            _run_file,
            path=path,
            settings=settings,
            langs=langs,
            outputs=outputs,
            progress=RichProgress(),
        )
        return

    build(targets(), outputs, RichProgress())
    show_output_dirs(settings, langs, outputs, open_dir=open)
