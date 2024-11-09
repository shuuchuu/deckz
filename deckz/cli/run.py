from pathlib import Path

from . import app


@app.command()
def run(
    targets: list[str] | None = None,
    /,
    *,
    handout: bool = True,
    presentation: bool = True,
    print: bool = True,  # noqa: A002
    workdir: Path = Path(),
) -> None:
    """Compile main targets.

    Args:
        targets: Restrict compilation to these targets
        handout: Produce PDFs without animations
        presentation: Produce PDFs with animations
        print: Produce printable PDFs
        workdir: Path to move into before running the command

    """
    from ..configuring.paths import Paths
    from ..running import run as running_run

    paths = Paths.from_defaults(workdir)
    running_run(
        paths=paths,
        build_handout=handout,
        build_presentation=presentation,
        build_print=print,
        target_whitelist=targets,
    )
