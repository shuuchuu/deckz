from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import cached_property
from pathlib import Path
from types import ModuleType
from typing import Any

from jinja2 import BaseLoader, Environment, TemplateNotFound

from ..models import AssetsMetadata
from ..utils import import_module_from_path
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


def _content_suffix(path: Path) -> str:
    # E.g. ".tex" for "foo.tex" (a main template) or "foo.tex.j2" (a
    # dependency about to be rendered in place), ".md" for "foo.md.j2".
    return path.with_suffix("").suffix if path.suffix == ".j2" else path.suffix


class Renderer(_BaseRenderer):
    """Render Jinja2 templates using a Jinja environment the target repo owns.

    `deckz` itself has no opinion on delimiters or filters -- including the \
    `image` macro or any other LaTeX/Markdown vocabulary -- since none of \
    that is generic. The target repo supplies a Python module (by \
    convention `templates/jinja2/env.py`, see \
    `GlobalPaths.jinja2_env_module`) exposing `environment_for(suffix: str) \
    -> jinja2.Environment`, called once per content-file suffix being \
    rendered (e.g. once for `.tex`, once for `.md`), so different sources \
    can use different delimiters/filters.

    The one thing `deckz` still injects into every render, regardless of \
    environment: an `assets_metadata_retriever` context variable (see \
    `AssetsMetadataRetrieverProtocol`). Any target-repo-defined filter that \
    references an asset file must call it to register that usage -- this is \
    what keeps `deckz asset search`/`deckz asset deps` and the i18n tooling \
    accurate.
    """

    def __init__(
        self, jinja_env_module: Path, global_factory: GlobalFactoryProtocol
    ) -> None:
        self._jinja_env_module_path = jinja_env_module
        self._global_factory = global_factory
        self._environments: dict[str, Environment] = {}

    def render_to_str(
        self, template_path: Path, /, **template_kwargs: Any
    ) -> tuple[str, AssetsMetadata]:
        env = self.environment_for(_content_suffix(template_path))
        template = env.get_template(str(template_path))
        assets_metadata_retriever = self._global_factory.assets_metadata_retriever()
        return (
            template.render(
                assets_metadata_retriever=assets_metadata_retriever,
                **template_kwargs,
            ),
            assets_metadata_retriever.assets_metadata,
        )

    def environment_for(self, suffix: str) -> Environment:
        """The target repo's Jinja environment for a content suffix (e.g. `.tex`).

        Exposed beyond `render_to_str`'s own use so other code (e.g. the \
        `deckz check variables` static analyzer) can parse a fragment with \
        the exact same delimiters/filters a real render would use, without \
        duplicating `templates/jinja2/env.py`'s loading.

        Returns:
            The environment, memoized per suffix.
        """
        if suffix not in self._environments:
            env = self._module.environment_for(suffix)
            env.loader = _AbsoluteLoader()
            self._environments[suffix] = env
        return self._environments[suffix]

    @cached_property
    def _module(self) -> ModuleType:
        return import_module_from_path(self._jinja_env_module_path, "deckz._jinja_env")
