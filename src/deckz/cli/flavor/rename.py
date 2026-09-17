from pathlib import Path

from . import app


@app.command()
def rename(
    section: str,
    old: str,
    new: str,
    /,
    *,
    dry_run: bool = False,
    workdir: Path = Path(),
) -> None:
    """Rename a section's flavor and rewrite all its usages.

    Every reference to the flavor, in every deck and section of the repository, \
    is rewritten to use the new name instead.

    Args:
        section: Path of the section the flavor belongs to
        old: Current name of the flavor
        new: New name for the flavor
        dry_run: Only validate the rename, without applying it
        workdir: Path to move into before running the command

    """
    from pathlib import PurePath

    from rich.console import Console

    from ...analyzing.flavor_renamer import FlavorRenamer
    from ...configuring.settings import GlobalSettings
    from ...models import FlavorName, UnresolvedPath

    console = Console(highlight=False)
    settings = GlobalSettings.from_yaml(workdir)
    flavor_renamer = FlavorRenamer(
        settings.paths.git_dir, settings.paths.shared_latex_dir
    )

    with console.status(f"Renaming {section}@{old}"):
        renamed = flavor_renamer.rename(
            UnresolvedPath(PurePath(section)),
            FlavorName(old),
            FlavorName(new),
            dry_run=dry_run,
        )

    if not renamed:
        console.print("Nothing to do: old and new names are identical")
        return

    verb = "Would rename" if dry_run else "Renamed"
    console.print(f"{verb} [bold]{section}[/]: {old} → [bold green]{new}[/]")
