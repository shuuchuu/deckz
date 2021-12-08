from pathlib import Path
from re import compile as re_compile

from typer import Argument, Option

from deckz.cli import app
from deckz.paths import GlobalPaths


@app.command()
def img_deps(
    image: str = Argument(
        ..., help="Image to track, like img/turing or tikz/variables"
    ),
    workdir: Path = Option(
        Path("."), help="Path to move into before running the command"
    ),
) -> None:
    """Find which latex files use an image."""
    paths = GlobalPaths.from_defaults(workdir)
    pattern = re_compile(fr'(\\V{{\[?"{image}".*\]? \| image}})')
    shared_latex_dir = paths.shared_latex_dir
    for f in shared_latex_dir.rglob("*.tex"):
        if pattern.search(f.read_text(encoding="utf8")):
            print(f.relative_to(shared_latex_dir))
