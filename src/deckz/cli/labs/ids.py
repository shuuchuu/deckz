from pathlib import Path

from . import app


@app.command()
def ids(*, dry_run: bool = False, workdir: Path = Path()) -> None:
    """Give every lab notebook without a published ID a new one.

    The ID is spelled out from where the notebook sits under the configured
    notebooks directory when it gets it, since Colab shows the published
    file name as the browser tab's title; a notebook can then move freely
    without breaking its published link (see `deckz labs publish`). Refuses
    to assign one that's already taken, or if an existing ID is used by
    several notebooks.

    Args:
        dry_run: Only list the IDs that would be assigned, without writing
            them
        workdir: Path to move into before running the command

    """
    from rich.console import Console

    from ...configuring.settings import GlobalSettings
    from ...labs.ids import assign_ids

    settings = GlobalSettings.from_yaml(workdir)
    console = Console(highlight=False)
    assigned = assign_ids(
        settings.paths.labs_notebooks_dir,
        settings.paths.content_dir,
        id_metadata_key=settings.labs.id_metadata_key,
        id_pattern=settings.labs.id_pattern,
        dry_run=dry_run,
    )

    if not assigned:
        console.print("Every notebook already has an ID.")
        return

    for lab_id, path in assigned:
        console.print(f"{lab_id}  [link=file://{path}]{path}[/link]")

    plural = "s" * (len(assigned) > 1)
    verb = "Would assign" if dry_run else "Assigned"
    console.print(f"\n{verb} {len(assigned)} ID{plural}")
