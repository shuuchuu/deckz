from itertools import chain
from pathlib import Path
from re import Pattern
from re import compile as re_compile
from typing import Iterator, Optional

from typer import Argument, Option

from deckz.cli import app
from deckz.paths import GlobalPaths, decks_paths


@app.command()
def img_deps(
    image: Optional[str] = Argument(
        None, help="Specific image to track, like img/turing or tikz/variables"
    ),
    workdir: Path = Option(
        Path("."), help="Path to move into before running the command"
    ),
) -> None:
    """Find which latex files use an image."""
    if image is not None:
        track_specific_image(image, workdir)


def track_specific_image(image: str, workdir: Path) -> None:
    pattern = re_compile(fr'(\\V{{\[?"{image}".*\]? \| image}})')
    global_paths = GlobalPaths.from_defaults(workdir)
    for directory in chain(
        [global_paths.shared_latex_dir],
        (paths.local_latex_dir for paths in decks_paths(workdir)),
    ):
        for f in _search_directory(directory, image, pattern):
            print(f.relative_to(global_paths.current_dir))


def _search_directory(directory: Path, image: str, pattern: Pattern) -> Iterator[Path]:
    for f in directory.rglob("*.tex"):
        if pattern.search(f.read_text(encoding="utf8")):
            yield f
