from functools import partial, reduce
from multiprocessing import Pool
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..components import AssetsSearcher, Renderer
from ..components.deck_building import PartDependenciesNodeVisitor
from ..configuring.settings import PathFromSettings
from ..models import Deck, ResolvedPath
from ..utils import all_decks


class _DefaultAssetsSearcherExtraKwArgs(BaseModel):
    model_config = ConfigDict(validate_default=True)

    assets_dir: PathFromSettings = "paths.shared_dir"  # type: ignore[assignment]
    git_dir: PathFromSettings = "paths.git_dir"  # type: ignore[assignment]
    renderer_key: str = "default"


class DefaultAssetsSearcher(
    AssetsSearcher, key="default", extra_kwargs_class=_DefaultAssetsSearcherExtraKwArgs
):
    def __init__(self, assets_dir: Path, git_dir: Path, renderer_key: str) -> None:
        self._assets_dir = assets_dir
        self._git_dir = git_dir
        self._renderer = self.new_dep(Renderer, renderer_key)

    def search(self, asset: str) -> set[ResolvedPath]:
        f = partial(self._deck_asset_dependencies, asset=asset)
        with Pool() as pool:
            return reduce(
                set.union,
                pool.map(f, all_decks(self._git_dir).values()),
                set(),
            )

    def _deck_asset_dependencies(self, deck: Deck, asset: str) -> set[ResolvedPath]:
        renderer = self.new_dep(Renderer, "default")
        result = set()
        deps = PartDependenciesNodeVisitor().process(deck)
        for part_deps in deps.values():
            for part_dep in part_deps:
                _, assets_usage = renderer.render_to_str(part_dep)
                if asset in assets_usage:
                    result.add(part_dep)
        return result
