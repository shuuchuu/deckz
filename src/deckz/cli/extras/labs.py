from pathlib import Path

from . import app


@app.command()
def labs(
    notebooks: list[Path],
    /,
    *,
    dry_run: bool = False,
) -> None:
    """Normalize Jupyter notebooks to this project's Colab conventions.

    Collapses every "Solution" markdown heading cell and disables Colab's \
    generative AI features, for every notebook found at or under each of \
    NOTEBOOKS (a file, or a directory searched recursively for `*.ipynb`).

    Args:
        notebooks: Notebook files, or directories to search recursively \
            for notebook files
        dry_run: Only list the notebooks that would change, without \
            writing them

    """
    from rich.console import Console

    from ...extras.labs import normalize_notebook, notebook_paths

    console = Console(highlight=False)
    changed = [
        path
        for path in notebook_paths(notebooks)
        if normalize_notebook(path, dry_run=dry_run)
    ]

    if not changed:
        console.print("No notebook to normalize!")
        return

    for path in changed:
        console.print(f"[link=file://{path}]{path}[/link]")

    plural = "s" * (len(changed) > 1)
    verb = "Would normalize" if dry_run else "Normalized"
    console.print(f"\n{verb} {len(changed)} notebook{plural}")
