from pathlib import Path
from re import compile as re_compile

from deckz.cli import app
from deckz.paths import GlobalPaths


@app.command()
def img_deps(
    image: str,
    path: Path = Path("."),
) -> None:
    """Find which latex files use an image."""
    paths = GlobalPaths.from_defaults(path)
    pattern = re_compile(fr'(\\V{{\[?"{image}".*\]? \| image}})')
    shared_latex_dir = paths.shared_latex_dir
    for f in shared_latex_dir.rglob("*.tex"):
        if pattern.search(f.read_text(encoding="utf8")):
            print(f.relative_to(shared_latex_dir))
