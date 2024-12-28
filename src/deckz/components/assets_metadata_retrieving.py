from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..components import AssetsMetadataRetriever
from ..configuring.settings import PathFromSettings
from ..models import AssetsUsage
from ..utils import load_yaml


class _DefaultAssetsMetadataRetrieverExtraKwArgs(BaseModel):
    model_config = ConfigDict(validate_default=True)

    assets_dir: PathFromSettings = "paths.shared_dir"  # type: ignore[assignment]


class DefaultAssetsMetadataRetriever(
    AssetsMetadataRetriever,
    key="default",
    extra_kwargs_class=_DefaultAssetsMetadataRetrieverExtraKwArgs,
):
    def __init__(self, assets_dir: Path) -> None:
        self._assets: AssetsUsage = {}
        self._assets_dir = assets_dir

    @property
    def assets(self) -> AssetsUsage:
        return self._assets

    def __call__(self, value: str) -> dict[str, Any] | None:
        self.assets[value] = self.assets.setdefault(value, 0) + 1
        metadata_path = (self._assets_dir / Path(value)).with_suffix(".yml")
        return load_yaml(metadata_path) if metadata_path.exists() else None
