from pathlib import Path

from . import app


@app.command()
def all(  # ruff: ignore[builtin-variable-shadowing]
    *,
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    html: bool = False,
    en: bool = False,
    dry_run: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile `run shared`'s deck, plus every deck-local override.

    For every real deck that locally overrides at least one file of a
    shared section, adds one extra copy of that section using the deck's
    own file in place of the shared one -- all in the same single compile
    as `run shared`.

    Args:
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        html: Produce an HTML deck (whole deck, with a table of contents)
        en: Compile the English variant
        dry_run: Only print the outputs that would be compiled and the content
            fragments each would re-render, without building anything
        workdir: Path to move into before running the command

    """
    from ...pipelines import OutputKinds, all_targets, build
    from .._presentation import RichProgress, print_plan_of

    lang = "en" if en else "fr"
    outputs = OutputKinds(
        handout=handout, presentation=presentation, print=print, html=html
    )
    targets = all_targets(workdir, lang)
    if dry_run:
        print_plan_of(targets, lang, outputs)
    else:
        build(targets, lang, outputs, RichProgress())
