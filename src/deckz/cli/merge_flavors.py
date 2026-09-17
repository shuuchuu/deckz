from pathlib import Path

from . import app


@app.command()
def merge_flavors(*, dry_run: bool = False, workdir: Path = Path()) -> None:
    """Merge sections' flavors that are identical up to their name.

    For every group of flavors of a section sharing the exact same title and \
    includes, only the first one is kept: the others are deleted, and every \
    reference to them, in every deck and section of the repository, is rewritten \
    to point to the kept flavor instead.

    Args:
        dry_run: Only report the merges that would be made, without applying them
        workdir: Path to move into before running the command

    """
    from rich.console import Console

    from ..analyzing.flavors_merger import FlavorsMerger
    from ..configuring.settings import GlobalSettings

    console = Console(highlight=False)
    settings = GlobalSettings.from_yaml(workdir)
    flavors_merger = FlavorsMerger(
        settings.paths.git_dir, settings.paths.shared_latex_dir
    )

    with console.status("Finding identical flavors"):
        merges = flavors_merger.merge(dry_run=dry_run)

    if not merges:
        console.print("No identical flavors found!")
        return

    verb = "Found" if dry_run else "Merged"
    for merge in sorted(merges, key=lambda m: str(m.section)):
        removed = ", ".join(sorted(merge.removed))
        console.print(
            f"{verb} [bold]{merge.section}[/]: {removed} → [bold green]{merge.kept}[/]"
        )
