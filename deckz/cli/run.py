from pathlib import Path
from typing import List

from click import argument

from deckz.cli import app, option_workdir, options_output
from deckz.paths import Paths
from deckz.running import run as running_run


@app.command()
@argument("targets", nargs=-1)
@options_output(handout=True, presentation=True, print=True)
@option_workdir
def run(
    targets: List[str], handout: bool, presentation: bool, print: bool, workdir: Path
) -> None:
    """
    Compile main targets.

    Compiling can be restricted to given TARGETS.
    """
    paths = Paths.from_defaults(workdir)
    running_run(
        paths=paths,
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
        target_whitelist=targets or None,
    )
