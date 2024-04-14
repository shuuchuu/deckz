from pathlib import Path

from typing_extensions import Annotated

from . import HandoutOption, PresentationOption, PrintOption, WorkdirOption, app


@app.command()
def check_all(
    handout: Annotated[bool, HandoutOption] = False,
    presentation: Annotated[bool, PresentationOption] = True,
    print: Annotated[bool, PrintOption] = False,
    workdir: Annotated[Path, WorkdirOption] = Path("."),
) -> None:
    """Compile all shared slides (presentation only by default)."""
    from ..running import run_all as running_run_all

    running_run_all(
        directory=workdir,
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
    )
