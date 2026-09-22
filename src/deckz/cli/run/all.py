from pathlib import Path

from . import app


@app.command()
def all(  # ruff: ignore[builtin-variable-shadowing]
    *,
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    en: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile `run shared`'s deck, plus every deck-local override.

    For every real deck that locally overrides at least one file of a \
    shared section, adds one extra copy of that section using the deck's \
    own file in place of the shared one -- all in the same single compile \
    as `run shared`.

    Args:
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        en: Compile the English variant
        workdir: Path to move into before running the command

    """
    from ...pipelines import run_all as _run_all

    _run_all(
        directory=workdir,
        lang="en" if en else "fr",
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
    )
