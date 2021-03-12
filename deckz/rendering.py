from filecmp import cmp
from functools import cached_property
from os import unlink
from os.path import join as path_join
from pathlib import Path
from shutil import move
from tempfile import NamedTemporaryFile
from typing import Any, List

from jinja2 import Environment, FileSystemLoader
from yaml import safe_load

from deckz.paths import Paths


class Renderer:
    def __init__(self, paths: Paths):
        self._paths = paths

    def render(
        self, *, template_path: Path, output_path: Path, **template_kwargs: Any
    ) -> None:
        if template_path.is_absolute():
            template_path_string = str(template_path.relative_to(self._paths.git_dir))
        else:
            template_path_string = str(template_path)
        template = self._env.get_template(template_path_string)
        try:
            with NamedTemporaryFile("w", encoding="utf8", delete=False) as fh:
                fh.write(template.render(**template_kwargs))
                fh.write("\n")
            if not output_path.exists() or not cmp(fh.name, str(output_path)):
                move(fh.name, output_path)
        finally:
            try:
                unlink(fh.name)
            except FileNotFoundError:
                pass

    @cached_property
    def _env(self) -> Environment:
        env = Environment(
            loader=FileSystemLoader(searchpath=self._paths.git_dir),
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
        env.filters["path_join"] = lambda paths: path_join(*paths)
        env.filters["image"] = self._img
        return env

    def _to_camel_case(self, string: str) -> str:
        return "".join(substring.capitalize() or "_" for substring in string.split("_"))

    def _img(self, args: List[Any]) -> str:
        if not isinstance(args, list):
            path = args
            modifier = ""
            scale = ""
        else:
            if len(args) >= 1:
                path = args[0]
                modifier = ""
                scale = ""
            if len(args) >= 2:
                modifier = args[1]
                scale = "{1}"
            if len(args) >= 3:
                scale = "{%.2f}" % args[2]
        metadata_path = (self._paths.shared_img_dir / path).with_suffix(".yml")
        info = ""
        if metadata_path.exists():
            metadata = safe_load(metadata_path.read_text(encoding="utf8"))
            info = (
                f"[{metadata['title']}, {metadata['author']}, {metadata['license']}.]"
            )
        return r"\img%s%s{%s}%s" % (modifier, info, path, scale)
