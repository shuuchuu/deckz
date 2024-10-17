from pathlib import Path

from . import (
    HandoutOption,
    PresentationOption,
    PrintOption,
    TargetOption,
    WorkdirOption,
    app,
)


@app.command()
def run(
    targets: TargetOption,
    handout: HandoutOption = True,
    presentation: PresentationOption = True,
    print: PrintOption = True,
    workdir: WorkdirOption = Path("."),
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
