from pathlib import Path

from . import app


@app.command()
def check_all(
    *,
    handout: bool = False,
    presentation: bool = True,
    print: bool = False,  # noqa: A002
    workdir: Path = Path(),
) -> None:
    """Compile all shared slides (presentation only by default).

    Args:
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        workdir: Path to move into before running the command

    """
    from ..pipelines import run_all

    run_all(
        directory=workdir,
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
    )
