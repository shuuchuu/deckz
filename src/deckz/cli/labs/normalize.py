from pathlib import Path

from . import app


@app.command()
def normalize(
    notebooks: list[Path],
    /,
    *,
    dry_run: bool = False,
    workdir: Path = Path(),
) -> None:
    """Normalize Jupyter notebooks to their Colab conventions.

    Collapses every markdown heading cell matching the configured solution
    heading (`labs.solution_heading`, "Solution" by default) and disables
    Colab's generative AI features, for every notebook found at or under
    each of NOTEBOOKS (a file, or a directory searched recursively for
    `*.ipynb`).

    Args:
        notebooks: Notebook files, or directories to search recursively
            for notebook files
        dry_run: Only list the notebooks that would change, without
            writing them
        workdir: Path to move into before running the command

    """
    from rich.console import Console

    from ...configuring.settings import GlobalSettings
    from ...labs.normalize import normalize_notebook
    from ...labs.notebook import notebook_paths

    settings = GlobalSettings.from_yaml(workdir)
    console = Console(highlight=False)
    changed = [
        path
        for path in notebook_paths(notebooks)
        if normalize_notebook(
            path, solution_heading=settings.labs.solution_heading, dry_run=dry_run
        )
    ]

    if not changed:
        console.print("No notebook to normalize!")
        return

    for path in changed:
        console.print(f"[link=file://{path}]{path}[/link]")

    plural = "s" * (len(changed) > 1)
    verb = "Would normalize" if dry_run else "Normalized"
    console.print(f"\n{verb} {len(changed)} notebook{plural}")
