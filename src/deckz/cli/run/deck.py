from pathlib import Path

from ...models import LANGS, PartName
from .._options import Langs, given, unique
from . import app

_EVERY_OUTPUT = (
    "handout",
    "part_handouts",
    "presentation",
    "print",
    "html",
    "course_notes",
)
"""What `--all` turns on: `OutputKinds`' fields, but `sync`, which removes files."""


@app.command(name="deck")
@app.default
def run(
    *,
    parts: list[PartName] | None = None,
    all: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    handout: bool = True,
    presentation: bool = True,
    print: bool = True,  # ruff: ignore[builtin-argument-shadowing]
    html: bool = False,
    part_handouts: bool = True,
    sync: bool = True,
    course_notes: bool = False,
    langs: Langs = ("fr",),
    watch: bool = False,
    dry_run: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile the deck in WORKDIR (default).

    Args:
        parts: Restrict deck compilation to these parts
        all: Compile every output of this deck in every language, e.g. before
            `deckz upload`, whatever the environment or a .env file set: the
            handouts, part handouts, presentations, printable PDFs, HTML and
            course notes. An option given next to it still applies: --lang fr
            for a deck not translated yet, --no-html to skip one output.
            --sync isn't affected
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
        course_notes: Also compile the deck's course notes, whole whatever
            --parts, in the languages they have chapters in (see `deckz run
            course-notes`). With --no-handout --no-presentation --no-print,
            only them
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
    from dataclasses import replace
    from logging import getLogger

    from ...configuring.settings import DeckSettings
    from ...exceptions import DeckParsingError
    from ...pipelines import BuildTarget, OutputKinds, build, deck_targets
    from ...pipelines import run as _run
    from .._presentation import (
        RichProgress,
        announce_build,
        print_plan_of,
        warn_missing_chapters,
    )

    settings = DeckSettings.from_yaml(workdir)
    langs = LANGS if all and not given("lang") else unique(langs)
    outputs = OutputKinds(
        handout=handout,
        presentation=presentation,
        print=print,
        html=html,
        part_handouts=part_handouts,
        sync=sync,
        course_notes=course_notes,
    )
    if all:
        outputs = replace(
            outputs,
            **{
                kind: True
                for kind in _EVERY_OUTPUT
                if not given(kind.replace("_", "-"))
            },
        )
    announce_build(
        str(settings.paths.current_dir.relative_to(settings.paths.git_dir)),
        langs,
        outputs,
        every_output=all,
    )
    # Not with --all alone: a deck may well have no course notes, and nobody asked.
    if course_notes:
        warn_missing_chapters(settings, langs)

    def targets() -> list[BuildTarget]:
        try:
            return deck_targets(
                settings, langs, parts, course_notes=outputs.course_notes
            )
        except DeckParsingError:
            # The parsing error names a file, not the language that lacks it.
            if all and not given("lang"):
                getLogger(__name__).warning(
                    "--all builds every language: if a translation is missing, "
                    "`deckz i18n missing-en` lists what's left, and "
                    "`deckz run --all --lang fr` builds the French only"
                )
            raise

    if dry_run:
        print_plan_of(targets(), outputs)
        return

    if not watch:
        build(targets(), outputs, RichProgress())
        return

    from ...pipelines import watch as _watch

    logger = getLogger(__name__)
    logger.info("Watching the content, assets, current and user directories")
    to_watch = [
        settings.paths.content_dir,
        settings.paths.assets_dir,
        settings.paths.current_dir,
    ]
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
        _run,
        settings=settings,
        langs=langs,
        outputs=outputs,
        parts=parts,
        progress=RichProgress(),
    )
