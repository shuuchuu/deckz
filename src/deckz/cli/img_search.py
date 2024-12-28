from pathlib import Path
from typing import TYPE_CHECKING

from . import app

if TYPE_CHECKING:
    from ..configuring.settings import GlobalSettings
    from ..models import Deck, ResolvedPath


@app.command()
def img_search(image: str, /, *, workdir: Path = Path()) -> None:
    """Find which latex files use IMAGE.

    Args:
        image: Image to search in LaTeX files. Specify the path relative to the shared \
            directory and whithout extension, e.g. img/turing
        workdir: Path to move into before running the command

    """
    from functools import partial, reduce
    from multiprocessing import Pool

    from rich.console import Console

    from ..configuring.settings import GlobalSettings
    from ..models import ResolvedPath
    from ..utils import all_decks

    settings = GlobalSettings.from_yaml(workdir)

    console = Console(highlight=False)
    with console.status("Processing decks"):
        decks = all_decks(settings.paths.git_dir).values()

        f = partial(_process_deck, image, settings=settings)
        with Pool() as pool:
            result: set[ResolvedPath] = reduce(set.union, pool.map(f, decks), set())

    for path in result:
        console.print(
            f"[link=file://{path}]{path.relative_to(settings.paths.git_dir)}[/link]"
        )


def _process_deck(
    image: str, deck: "Deck", settings: "GlobalSettings"
) -> set["ResolvedPath"]:
    from ..components import Renderer
    from ..components.deck_building import PartDependenciesNodeVisitor

    renderer = Renderer.new("default", settings)
    result = set()
    deps = PartDependenciesNodeVisitor().process(deck)
    for part_deps in deps.values():
        for part_dep in part_deps:
            _, assets_usage = renderer.render_to_str(part_dep)
            if image in assets_usage:
                result.add(part_dep)
    return result
