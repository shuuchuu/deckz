from pathlib import Path

from . import app


@app.command()
def fmt(
    notebooks: list[Path] | None = None,
    /,
    *,
    check: bool = False,
    workdir: Path = Path(),
) -> None:
    """Rewrite every notebook in deckz's canonical JSON style.

    Notebooks come in two styles in the wild (Jupyter's `indent=1`, Colab's
    compact one-line): this makes every one of NOTEBOOKS (default: the
    configured notebooks directory) use one style (indent 1, sorted keys,
    every cell's source as a list of lines), so a notebook saved from Colab
    is reformatted once and every later diff stays small, whoever edits it
    next.

    Args:
        notebooks: Notebook files, or directories to search recursively for
            notebook files; defaults to the configured notebooks directory
        check: Only list the notebooks that would change, without writing
            them, and exit with an error if any would
        workdir: Path to move into before running the command

    """
    from rich.console import Console

    from ...configuring.settings import GlobalSettings
    from ...labs.notebook import fmt_notebook, notebook_paths

    settings = GlobalSettings.from_yaml(workdir)
    targets = notebooks or [settings.paths.labs_notebooks_dir]
    console = Console(highlight=False)
    changed = [
        path
        for path in notebook_paths(targets)
        if fmt_notebook(path, heading=settings.labs.solution_heading, dry_run=check)
    ]

    if not changed:
        console.print("Every notebook is already canonical.")
        return

    for path in changed:
        console.print(f"[link=file://{path}]{path}[/link]")

    plural = "s" * (len(changed) > 1)
    verb = "Would reformat" if check else "Reformatted"
    console.print(f"\n{verb} {len(changed)} notebook{plural}")

    if check:
        from sys import exit as sys_exit

        sys_exit(1)
