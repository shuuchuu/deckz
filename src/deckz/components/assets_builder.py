from collections.abc import Iterable
from functools import cached_property
from pathlib import Path

from ..exceptions import HookError
from .hooks import load_hook
from .protocols import AssetsBuilderProtocol, CompilerProtocol


class AssetsBuilder(AssetsBuilderProtocol):
    """Build project-specific assets (matplotlib/plotly figures, ...).

    `deckz` itself has no opinion on what assets a deck needs or how to \
    build them. The target repo supplies a Python module (by convention \
    `templates/assets_builders.py`, see `GlobalPaths.assets_builders_module`) \
    exposing:

        def assets_builders(
            assets_dir: Path, compiler: CompilerProtocol
        ) -> Iterable[AssetsBuilderProtocol]: ...

    called once to obtain every builder to run. Each builder writes its \
    output somewhere under `assets_dir` -- deckz core symlinks every \
    top-level directory found there into every build directory, without \
    needing to know their names. See [`hooks`][deckz.components.hooks] for \
    the contract's versioning and trust boundary.
    """

    def __init__(
        self,
        assets_builders_module: Path,
        assets_dir: Path,
        compiler: CompilerProtocol,
    ) -> None:
        self._assets_builders_module_path = assets_builders_module
        self._assets_dir = assets_dir
        self._compiler = compiler

    def build_assets(self) -> None:
        for assets_builder in self._builders:
            assets_builder.build_assets()

    def watched_dirs(self) -> Iterable[Path]:
        return {d for b in self._builders for d in b.watched_dirs()}

    @cached_property
    def _builders(self) -> list[AssetsBuilderProtocol]:
        path = self._assets_builders_module_path
        hook = load_hook(path, "deckz._assets_builders", "assets_builders")
        builders = list(hook(self._assets_dir, self._compiler))
        for builder in builders:
            if not all(
                callable(getattr(builder, method, None))
                for method in ("build_assets", "watched_dirs")
            ):
                msg = (
                    f"{path}: assets_builders returned {builder!r}, which lacks "
                    "a build_assets or watched_dirs method"
                )
                raise HookError(msg)
        return builders
