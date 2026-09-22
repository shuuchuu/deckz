from pathlib import Path

from . import app


@app.command(name="shared")
def run_shared(
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
    named flavor happens to list. Much faster than `run decks`: use this \
    while editing shared content without waiting for a full repository \
    compile.

    Args:
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        en: Compile the English variant
        workdir: Path to move into before running the command

    """
    from ...pipelines import run_shared as _run_shared

    _run_shared(
        directory=workdir,
        lang="en" if en else "fr",
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
    )
