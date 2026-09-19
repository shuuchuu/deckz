from pathlib import Path

from . import app


@app.command(name="shared")
def check_shared(
    *,
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    en: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile every shared section at once, in one throwaway deck.

    Each section is expanded to a synthetic "all files" flavor: every file \
    physically in the section's own directory, not just the ones some real \
    named flavor happens to list. Much faster than `check decks`: use this \
    while editing shared content without waiting for a full repository \
    compile.

    Args:
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        en: Compile the English variant
        workdir: Path to move into before running the command

    """
    from ...pipelines import check_shared as _check_shared

    _check_shared(
        directory=workdir,
        lang="en" if en else "fr",
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
    )
