from pathlib import Path
from sys import executable

from . import app


@app.command()
def check(
    notebooks: list[Path],
    /,
    *,
    smoke: bool = False,
    python: str = executable,
    timeout: int = 300,
    workdir: Path = Path(),
) -> None:
    """Structural checks and an execution of every notebook's code cells.

    Structural: a solution heading not collapsed in Colab, an empty
    solution section, a stored error output. Execution: every code cell of
    NOTEBOOKS (a file, or a directory searched recursively for `*.ipynb`)
    runs in order, in a throwaway directory, reporting which cells raise.

    Args:
        notebooks: Notebook files, or directories to search recursively
            for notebook files
        smoke: Cap every Lightning Trainer (1 epoch, a few batches) so a
            CPU run finishes
        python: Interpreter to run the cells with, e.g. a throwaway venv
            with the labs' libraries installed (this process's own may not
            have them)
        timeout: Seconds bounding the whole notebook's execution
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...labs.execution import check_notebook
    from ...labs.notebook import notebook_paths

    settings = GlobalSettings.from_yaml(workdir)
    for path in notebook_paths(notebooks):
        print(f"#### {path}")
        for line in check_notebook(
            path,
            heading=settings.labs.solution_heading,
            python=python,
            smoke=smoke,
            timeout=timeout,
        ):
            print(line)
        print()
