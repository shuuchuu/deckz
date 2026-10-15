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
    container: bool = False,
    timeout: int = 300,
    workdir: Path = Path(),
) -> None:
    """Structural checks and an execution of every notebook's code cells.

    Structural: a solution heading not collapsed in Colab, an empty
    solution section, a stored error output. Execution: every code cell of
    NOTEBOOKS (a file, or a directory searched recursively for `*.ipynb`)
    runs in order, in a throwaway directory, reporting which cells raise.
    It mirrors Colab's shell lines and magics, but runs only harmless data
    fetches among the shell commands; `--container` runs everything, in the
    published repository's dev container (what Codespaces opens, built from
    `labs/published/.devcontainer/`; needs Docker).

    Args:
        notebooks: Notebook files, or directories to search recursively
            for notebook files
        smoke: Cap every Lightning Trainer (1 epoch, a few batches) so a
            CPU run finishes
        python: Interpreter to run the cells with, e.g. a throwaway venv
            with the labs' libraries installed (this process's own may not
            have them)
        container: Run each notebook for real in the published
            repository's dev container, under its published name, instead
            of with PYTHON
        timeout: Seconds bounding the whole notebook's execution
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...labs.container import dev_container
    from ...labs.execution import check_notebook
    from ...labs.notebook import notebook_paths
    from ...labs.publishing import notebook_id, repository_name

    settings = GlobalSettings.from_yaml(workdir)
    dev = (
        dev_container(
            settings.paths.labs_published_dir,
            repository_name(settings.paths.git_dir, settings.labs.publish_remote),
        )
        if container
        else None
    )
    for path in notebook_paths(notebooks):
        print(f"#### {path}")
        lab_id = notebook_id(path, settings.labs.id_metadata_key)
        for line in check_notebook(
            path,
            heading=settings.labs.solution_heading,
            python=python,
            smoke=smoke,
            timeout=timeout,
            container=dev,
            name=f"{lab_id}.ipynb" if lab_id else None,
        ):
            print(line)
        print()
