from collections.abc import Callable
from functools import cached_property
from os.path import join as path_join
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment, TemplateNotFound, pass_context
from jinja2.runtime import Context
from pydantic import BaseModel, ConfigDict, Field

from ..components import AssetsMetadataRetriever
from ..configuring.settings import PathFromSettings
from ..models import AssetsUsage
from . import Renderer


class _AbsoluteLoader(BaseLoader):
    def get_source(
        self, environment: Environment, template: str
    ) -> tuple[str, str, Callable[[], bool]]:
        template_path = Path(template)
        if not template_path.exists():
            raise TemplateNotFound(template)
        mtime = template_path.stat().st_mtime
        source = template_path.read_text(encoding="utf8")
        return (
            source,
            str(template_path),
            lambda: mtime == template_path.stat().st_mtime,
        )


class _LocalizedValues(BaseModel):
    fr: dict[str, str] = Field(default_factory=dict)
    en: dict[str, str] = Field(default_factory=dict)
    all: dict[str, str] = Field(default_factory=dict)

    def get_default(self, value: str, lang: str) -> str:
        if lang == "fr" and value in self.fr:
            return self.fr[value]
        if lang == "en" and value in self.en:
            return self.en[value]
        return self.all.get(value, value)


class _DefaultImageValues(BaseModel):
    license: _LocalizedValues = Field(default_factory=_LocalizedValues)
    author: _LocalizedValues = Field(default_factory=_LocalizedValues)
    title: _LocalizedValues = Field(default_factory=_LocalizedValues)


class _DefaultRendererExtraKwArgs(BaseModel):
    model_config = ConfigDict(validate_default=True)

    default_img_values: _DefaultImageValues = Field(default_factory=_DefaultImageValues)
    assets_dir: PathFromSettings = "paths.shared_dir"  # type: ignore[assignment]


class DefaultRenderer(
    Renderer, key="default", extra_kwargs_class=_DefaultRendererExtraKwArgs
):
    def __init__(
        self, default_img_values: _DefaultImageValues, assets_dir: Path
    ) -> None:
        self._default_img_values = default_img_values
        self._assets_dir = assets_dir

    def render_to_str(
        self, template_path: Path, /, **template_kwargs: Any
    ) -> tuple[str, AssetsUsage]:
        template = self._env.get_template(str(template_path))
        assets_metadata_retriever = self.new_dep(AssetsMetadataRetriever, "default")
        return (
            template.render(
                assets_metadata_retriever=assets_metadata_retriever,
                **template_kwargs,
            ),
            assets_metadata_retriever.assets,
        )

    @cached_property
    def _env(self) -> Environment:
        env = Environment(
            loader=_AbsoluteLoader(),
            block_start_string=r"\BLOCK{",
            block_end_string="}",
            variable_start_string=r"\V{",
            variable_end_string="}",
            comment_start_string=r"\#{",
            comment_end_string="}",
            line_statement_prefix="%%",
            line_comment_prefix="%#",
            trim_blocks=True,
            autoescape=False,
        )
        env.filters["camelcase"] = self._to_camel_case
        env.filters["path_join"] = lambda paths: path_join(*paths)  # noqa: PTH118
        env.filters["image"] = self._img
        return env

    def _to_camel_case(self, string: str) -> str:
        return "".join(substring.capitalize() or "_" for substring in string.split("_"))

    @pass_context
    def _img(
        self,
        context: Context,
        value: str,
        modifier: str = "",
        scale: float = 1.0,
        lang: str = "fr",
    ) -> str:
        metadata = context["assets_metadata_retriever"](value)
        if metadata is not None:

            def get_en_or_fr(key: str) -> str:
                if lang != "fr":
                    key_en = f"{key}_en"
                    return metadata[key_en] if key_en in metadata else metadata[key]
                return metadata[key]

            title = self._default_img_values.title.get_default(
                get_en_or_fr("title"), lang
            )
            author = self._default_img_values.author.get_default(
                get_en_or_fr("author"), lang
            )
            license_name = self._default_img_values.license.get_default(
                get_en_or_fr("license"), lang
            )
            info = f"[{title}, {author}, {license_name}.]"
        else:
            info = ""

        return f"\\img{modifier}{info}{{{value}}}{{{scale:.2f}}}"
