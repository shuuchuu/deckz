from collections.abc import Iterable
from pathlib import Path

from click import argument

from . import app, option_workdir, options_output


@app.command()
@argument("targets", nargs=-1)
@options_output(handout=True, presentation=True, print=True)
@option_workdir
def run(
    targets: Iterable[str],
    handout: bool,
    presentation: bool,
    print: bool,
    workdir: Path,
) -> None:
    """
    Compile main targets.

    Compiling can be restricted to given TARGETS.
    """
    from ..paths import Paths
    from ..running import run as running_run

    paths = Paths.from_defaults(workdir)
    running_run(
        paths=paths,
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
        target_whitelist=targets or None,
    )
