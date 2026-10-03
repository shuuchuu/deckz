from pathlib import Path

from . import app


@app.command(name="decks")
def run_decks(
    *,
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    html: bool = False,
    en: bool = False,
    dry_run: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile every deck in the repository, end to end.

    By far the slowest of the three `run` validation subcommands on a repo
    with many decks: every shared section gets recompiled once per deck
    that includes it, rather than once. Prefer `run shared` or `run all`
    while iterating on shared content.

    Args:
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        html: Produce an HTML deck (whole deck, with a table of contents)
        en: Compile the English variant of every deck. Strict across the
            whole repository: the first deck missing any translation aborts
            the whole run
        dry_run: Only print the outputs that would be compiled and the content
            fragments each would re-render, without building anything
        workdir: Path to move into before running the command

    """
    from ...pipelines import OutputKinds, build, decks_targets
    from .._presentation import RichProgress, print_plan_of

    lang = "en" if en else "fr"
    outputs = OutputKinds(
        handout=handout, presentation=presentation, print=print, html=html
    )
    targets = decks_targets(workdir, lang)
    if dry_run:
        print_plan_of(targets, lang, outputs)
    else:
        build(targets, lang, outputs, RichProgress())
