from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..components import AssetsMetadataRetriever
from ..configuring.settings import PathFromSettings
from ..models import AssetsMetadata
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
        self._assets_metadata: AssetsMetadata = {}
        self._assets_dir = assets_dir

    @property
    def assets_metadata(self) -> AssetsMetadata:
        return self._assets_metadata

    def __call__(self, value: str) -> dict[str, Any] | None:
        metadata_path = (self._assets_dir / Path(value)).with_suffix(".yml")
        metadata = load_yaml(metadata_path) if metadata_path.exists() else None
        self.assets_metadata[value] = (
            *self.assets_metadata.setdefault(value, ()),
            metadata,
        )
        return metadata
