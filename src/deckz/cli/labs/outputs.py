from pathlib import Path

from . import app


@app.command()
def outputs(executed: Path, notebook: Path, /, *, workdir: Path = Path()) -> None:
    """Write an executed copy's outputs back into a notebook, cell by cell.

    Copies only each code cell's outputs and execution count from EXECUTED
    into NOTEBOOK (no run metadata), merging consecutive stream outputs and
    resolving carriage returns, so a progress bar is stored once, as its
    final state, as Colab shows it. Then writes NOTEBOOK back in deckz's
    canonical style.

    Args:
        executed: Path to the executed copy, read for its cells' outputs
        notebook: Path to the notebook to update and save
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...labs.outputs import write_outputs

    settings = GlobalSettings.from_yaml(workdir)
    write_outputs(executed, notebook, solution_heading=settings.labs.solution_heading)
    print(f"Wrote outputs from {executed} into {notebook}")
