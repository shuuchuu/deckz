from pathlib import Path

from . import app


@app.command()
def check_all(
    *,
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    en: bool = False,
    workdir: Path = Path(),
) -> None:
    """Compile all shared slides (presentation only by default).

    Args:
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        en: Compile the English variant of every deck. Strict across the \
            whole repository: the first deck missing any translation aborts \
            the whole run
        workdir: Path to move into before running the command

    """
    from ..pipelines import run_all

    run_all(
        directory=workdir,
        lang="en" if en else "fr",
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
    )
