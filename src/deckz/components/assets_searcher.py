from functools import partial, reduce
from multiprocessing import Pool
from pathlib import Path

from ..models import Deck, ResolvedPath
from ..utils import all_decks
from .deck_builder import PartDependenciesNodeVisitor
from .protocols import AssetsSearcherProtocol, RendererProtocol


class AssetsSearcher(AssetsSearcherProtocol):
    def __init__(
        self, assets_dir: Path, git_dir: Path, renderer: RendererProtocol
    ) -> None:
        self._assets_dir = assets_dir
        self._git_dir = git_dir
        self._renderer = renderer

    def search(self, asset: str) -> set[ResolvedPath]:
        f = partial(self._deck_asset_dependencies, asset=asset)
        with Pool() as pool:
            return reduce(
                set.union,
                pool.map(f, all_decks(self._git_dir).values()),
                set(),
            )

    def _deck_asset_dependencies(self, deck: Deck, asset: str) -> set[ResolvedPath]:
        result = set()
        deps = PartDependenciesNodeVisitor().process(deck)
        for part_deps in deps.values():
            for part_dep in part_deps:
                _, assets_usage = self._renderer.render_to_str(part_dep)
                if asset in assets_usage:
                    result.add(part_dep)
        return result
