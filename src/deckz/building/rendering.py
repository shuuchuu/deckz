from collections.abc import Callable
from contextlib import suppress
from filecmp import cmp
from functools import cached_property
from os.path import join as path_join
from pathlib import Path
from shutil import move
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any

from jinja2 import BaseLoader, Environment, TemplateNotFound

from ..utils import load_yaml

if TYPE_CHECKING:
    from ..configuring.settings import DeckSettings


class AbsoluteLoader(BaseLoader):
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


class Renderer:
    def __init__(self, settings: "DeckSettings"):
        self._settings = settings

    def render(
        self, *, template_path: Path, output_path: Path, **template_kwargs: Any
    ) -> None:
        template = self._env.get_template(str(template_path))
        try:
            with NamedTemporaryFile("w", encoding="utf8", delete=False) as fh:
                fh.write(template.render(**template_kwargs))
                fh.write("\n")
            if not output_path.exists() or not cmp(fh.name, str(output_path)):
                move(fh.name, output_path)
        finally:
            with suppress(FileNotFoundError):
                Path(fh.name).unlink()

    @cached_property
    def _env(self) -> Environment:
        env = Environment(
            loader=AbsoluteLoader(),
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

    def _img(
        self, value: str, modifier: str = "", scale: float = 1.0, lang: str = "fr"
    ) -> str:
        metadata_path = (self._settings.paths.shared_dir / Path(value)).with_suffix(
            ".yml"
        )
        if metadata_path.exists():
            metadata = load_yaml(metadata_path)

            def get_en_or_fr(key: str) -> str:
                if lang != "fr":
                    key_en = f"{key}_en"
                    return metadata[key_en] if key_en in metadata else metadata[key]
                return metadata[key]

            title = self._settings.default_img_values.title.get_default(
                get_en_or_fr("title"), lang
            )
            author = self._settings.default_img_values.author.get_default(
                get_en_or_fr("author"), lang
            )
            license_name = self._settings.default_img_values.license.get_default(
                get_en_or_fr("license"), lang
            )
            info = f"[{title}, {author}, {license_name}.]"
        else:
            info = ""

        return f"\\img{modifier}{info}{{{value}}}{{{scale:.2f}}}"
