from pathlib import Path

from . import app


@app.command()
def img_search(
    image: str,
    /,
    *,
    workdir: Path = Path(),
) -> None:
    """Find which latex files use IMAGE.

    Args:
        image: Image to search in LaTeX files. Specify the path relative to the shared \
            directory and whithout extension, e.g. img/turing
        workdir: Path to move into before running the command

    """
    from re import VERBOSE
    from re import compile as re_compile

    from rich.console import Console

    from ..configuring.paths import GlobalPaths
    from ..utils import latex_dirs

    global_paths = GlobalPaths(current_dir=workdir)
    console = Console(highlight=False)
    pattern = re_compile(
        rf"""
        \\V{{
            \s*
            "{image}"
            \s*
            \|
            \s*
            image
            \s*
            (?:\([^)]*\))?
            \s*
          }}
        """,
        VERBOSE,
    )
    for latex_dir in latex_dirs(global_paths.git_dir, global_paths.shared_latex_dir):
        for f in latex_dir.rglob("*.tex"):
            if pattern.search(f.read_text(encoding="utf8")):
                console.print(
                    f"[link=file://{f}]{f.relative_to(global_paths.git_dir)}[/link]"
                )
