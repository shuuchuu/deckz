from pathlib import Path

from . import app


@app.command()
def latex(*, dry_run: bool = False, workdir: Path = Path()) -> None:
    """Delete unused LaTeX files, shared or local to a deck.

    Args:
        dry_run: Only list the files that would be deleted, without deleting them
        workdir: Path to move into before running the command

    """
    from logging import getLogger

    from rich.console import Console

    from ...analyzing.sections_analyzer import SectionsAnalyzer
    from ...configuring.settings import GlobalSettings

    logger = getLogger(__name__)
    console = Console(highlight=False)
    settings = GlobalSettings.from_yaml(workdir)
    sections_analyzer = SectionsAnalyzer(
        settings.paths.shared_latex_dir, settings.paths.git_dir, settings.file_extension
    )

    with console.status("Finding unused LaTeX files"):
        unused_files = sections_analyzer.unused_files()

    if not unused_files:
        console.print("No unused LaTeX file!")
        return

    git_dir = settings.paths.git_dir
    for path in sorted(unused_files):
        console.print(f"[link=file://{path}]{path.relative_to(git_dir)}[/link]")
        if not dry_run:
            path.unlink()

    plural = "s" * (len(unused_files) > 1)
    if dry_run:
        console.print(f"\n{len(unused_files)} unused LaTeX file{plural} found")
    else:
        logger.info(f"Deleted {len(unused_files)} unused LaTeX file{plural}")
