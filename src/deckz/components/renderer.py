from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import cached_property
from os.path import join as path_join
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment, TemplateNotFound, pass_context
from jinja2.runtime import Context

from ..configuring.settings import DefaultImageValues
from ..models import AssetsMetadata
from .protocols import GlobalFactoryProtocol, RendererProtocol


class _BaseRenderer(ABC, RendererProtocol):
    @abstractmethod
    def render_to_str(
        self, template_path: Path, /, **template_kwargs: Any
    ) -> tuple[str, AssetsMetadata]:
        raise NotImplementedError

    def render_to_path(
        self, template_path: Path, output_path: Path, /, **template_kwargs: Any
    ) -> AssetsMetadata:
        from contextlib import suppress
        from filecmp import cmp
        from shutil import move
        from tempfile import NamedTemporaryFile

        try:
            with NamedTemporaryFile("w", encoding="utf8", delete=False) as fh:
                rendered, assets_metadata = self.render_to_str(
                    template_path, **template_kwargs
                )
                fh.write(rendered)
                fh.write("\n")
            if not output_path.exists() or not cmp(fh.name, str(output_path)):
                move(fh.name, output_path)
        finally:
            with suppress(FileNotFoundError):
                Path(fh.name).unlink()
        return assets_metadata


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


class Renderer(_BaseRenderer):
    def __init__(
        self,
        default_img_values: DefaultImageValues,
        assets_dir: Path,
        global_factory: GlobalFactoryProtocol,
    ) -> None:
        self._default_img_values = default_img_values
        self._assets_dir = assets_dir
        self._global_factory = global_factory

    def render_to_str(
        self, template_path: Path, /, **template_kwargs: Any
    ) -> tuple[str, AssetsMetadata]:
        template = self._env.get_template(str(template_path))
        assets_metadata_retriever = self._global_factory.assets_metadata_retriever()
        return (
            template.render(
                assets_metadata_retriever=assets_metadata_retriever,
                **template_kwargs,
            ),
            assets_metadata_retriever.assets_metadata,
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
