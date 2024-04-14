from pathlib import Path

from typing_extensions import Annotated

from . import HandoutOption, PresentationOption, PrintOption, WorkdirOption, app


@app.command()
def run(
    targets: list[str],
    handout: Annotated[bool, HandoutOption] = True,
    presentation: Annotated[bool, PresentationOption] = True,
    print: Annotated[bool, PrintOption] = True,
    workdir: Annotated[Path, WorkdirOption] = Path("."),
) -> None:
    """
    Compile main targets.

    Compiling can be restricted to given TARGETS.
    """
    from ..configuring.paths import Paths
    from ..running import run as running_run

    paths = Paths.from_defaults(workdir)
    running_run(
        paths=paths,
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
        target_whitelist=targets or None,
    )
