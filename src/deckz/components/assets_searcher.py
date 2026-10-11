from functools import partial, reduce
from pathlib import Path
from typing import get_args

from ..models import Lang, ParsedDeck, ResolvedPath
from ..utils import all_decks, create_pool
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
        # en decks can reference assets their fr counterparts don't.
        decks = [
            parsed
            for lang in get_args(Lang)
            for parsed in all_decks(self._git_dir, lang).values()
        ]
        with create_pool() as pool:
            return reduce(set.union, pool.map(f, decks), set())

    def _deck_asset_dependencies(
        self, parsed: ParsedDeck, asset: str
    ) -> set[ResolvedPath]:
        result = set()
        deps = PartDependenciesNodeVisitor().process(parsed.deck)
        for part_deps in deps.values():
            for part_dep in part_deps:
                _, assets_usage = self._renderer.render_to_str(
                    part_dep, variables=parsed.variables
                )
                if asset in assets_usage:
                    result.add(part_dep)
        return result
