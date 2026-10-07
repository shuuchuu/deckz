from pathlib import Path

from . import app


@app.command()
def compare(
    lab_dirs: list[Path] | None = None,
    /,
    *,
    workdir: Path = Path(),
) -> None:
    """Report structural differences between fr/en lab notebook pairs.

    For every fr/en pair (every pair under the configured notebooks
    directory by default, or under LAB_DIRS), reports cell count, cell
    types, and code cells that differ beyond what a translation changes
    (comments, string literals, and identifiers renamed consistently within
    the cell).

    Args:
        lab_dirs: Restrict to the pairs under one of these directories
        workdir: Path to move into before running the command

    """
    from ...configuring.settings import GlobalSettings
    from ...labs.comparison import compare_pairs

    settings = GlobalSettings.from_yaml(workdir)
    roots = [path.resolve() for path in lab_dirs or ()]
    differing = 0
    for stem, problems in compare_pairs(settings.paths.labs_notebooks_dir, roots):
        differing += 1
        print(f"#### {stem}")
        print(*(f"  {p}" for p in problems), sep="\n")

    if differing:
        from sys import exit as sys_exit

        sys_exit(1)
