from pathlib import Path
from re import compile as re_compile

from click import argument
from rich.console import Console

from deckz.cli import app, option_workdir
from deckz.paths import GlobalPaths


@app.command()
@argument("image")
@option_workdir
def img_search(image: str, workdir: Path) -> None:
    """
    Find which latex files use IMAGE.

    Specify the specific image to track relative to the shared directory like img/turing
    """
    global_paths = GlobalPaths.from_defaults(workdir)
    console = Console(highlight=False)
    pattern = re_compile(rf'(\\V{{\[?"{image}".*\]? \| image}})')
    current_dir = global_paths.current_dir
    for latex_dir in global_paths.latex_dirs():
        for f in latex_dir.rglob("*.tex"):
            if pattern.search(f.read_text(encoding="utf8")):
                console.print(f"[link=file://{f}]{f.relative_to(current_dir)}[/link]")
