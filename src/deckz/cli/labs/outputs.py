from pathlib import Path

from . import app


@app.command()
def outputs(
    executed: Path,
    notebook: Path,
    /,
    *,
    max_image_kb: int = 200,
    no_recompress: bool = False,
    workdir: Path = Path(),
) -> None:
    """Write an executed copy's outputs back into a notebook, cell by cell.

    Copies only each code cell's outputs and execution count from EXECUTED
    into NOTEBOOK (no run metadata), merging consecutive stream outputs and
    resolving carriage returns, so a progress bar is stored once, as its
    final state, as Colab shows it. A large `image/png` output is also
    recompressed (re-encoded as JPEG, or re-saved as an optimized PNG when
    JPEG wouldn't shrink it enough), unless disabled. Then writes NOTEBOOK
    back in deckz's canonical style.

    Args:
        executed: Path to the executed copy, read for its cells' outputs
        notebook: Path to the notebook to update and save
        max_image_kb: Size, in KiB, above which a PNG output image is \
            considered for recompression
        no_recompress: Disable image recompression, keeping every output \
            exactly as EXECUTED produced it
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...labs.outputs import write_outputs

    settings = GlobalSettings.from_yaml(workdir)
    write_outputs(
        executed,
        notebook,
        solution_heading=settings.labs.solution_heading,
        recompress_images=not no_recompress,
        max_image_kb=max_image_kb,
    )
    print(f"Wrote outputs from {executed} into {notebook}")
