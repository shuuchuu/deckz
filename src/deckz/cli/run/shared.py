from pathlib import Path

from .._options import Langs, unique
from . import app


@app.command(name="shared")
def run_shared(
    *,
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    html: bool = False,
    part_handouts: bool = True,
    sync: bool = True,
    langs: Langs = ("fr",),
    dry_run: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile every shared section at once, in one throwaway deck.

    Each section is expanded to a synthetic "all files" flavor: every file
    physically in the section's own directory, not just the ones some real
    named flavor happens to list. Much faster than `run decks`: use this
    while editing shared content without waiting for a full repository
    compile.

    Args:
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
        dry_run: Only print the outputs that would be compiled and the content
            fragments each would re-render, without building anything
        workdir: Path to move into before running the command

    """
    from ...pipelines import OutputKinds, build, shared_targets
    from .._presentation import RichProgress, announce_build, print_plan_of

    langs = unique(langs)
    outputs = OutputKinds(
        handout=handout,
        presentation=presentation,
        print=print,
        html=html,
        part_handouts=part_handouts,
        sync=sync,
    )
    announce_build("every shared section", langs, outputs)
    targets = shared_targets(workdir, langs)
    if dry_run:
        print_plan_of(targets, outputs)
    else:
        build(targets, outputs, RichProgress())
