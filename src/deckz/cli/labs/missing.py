from pathlib import Path

from . import app


@app.command()
def missing(*, workdir: Path = Path()) -> None:
    """Report every lab notebook with no counterpart in the other language.

    Args:
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...labs.comparison import missing_notebooks

    settings = GlobalSettings.from_yaml(workdir)
    gaps = 0
    for path in missing_notebooks(settings.paths.labs_notebooks_dir):
        gaps += 1
        print(f"{path} missing")

    if gaps:
        from sys import exit as sys_exit

        sys_exit(1)
