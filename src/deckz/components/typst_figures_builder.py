"""A built-in assets builder for Typst figures, as one SVG per language.

Any Typst-themed repo can register it from its own `templates/assets_builders.py`
(see `AssetsBuilder`'s docstring): deckz has no opinion on where a figure's
text translation comes from or how a deck picks it up (this repo's own
`tr[fr][en]`/`_lib.typ` convention stays theme-specific), only on compiling
`.typ` figures to SVG, once per language, with the right include path.
"""

import re
from collections.abc import Iterable
from logging import getLogger
from pathlib import Path

from ..exceptions import DeckzError
from ..stamps import digest, is_fresh, stamp_path, write_stamp
from ..utils import copy_file_if_changed
from .protocols import AssetsBuilderProtocol

# A string literal on one line, not a package (`"@preview/cetz:0.5.2"`).
_STRING = re.compile(r'"([^"@\n][^"\n]*)"')


class TypstFiguresAssetsBuilder(AssetsBuilderProtocol):
    """Typst figures (e.g. `figures/typ`), as one SVG per language.

    Each figure becomes `<name>.<lang>.svg` in `output_dir`. Figures are
    compiled through `_svg.typ` (at `output_dir`'s root once build starts)
    with `assets_dir` as the Typst root, so they can address other assets
    (`/img`, `/typst`, ...) the way deck content does: their sources, every
    `_`-prefixed library and any non-`.typ` file alongside them (e.g. `.yml`
    credits) are mirrored into `output_dir` first. Typst draws SVG text as
    paths: no font to ship, but no selectable text either. Each SVG's
    stamp (`deckz.stamps`) covers its figure, the files it references
    (libraries, images, ...) and those `_svg.typ` does (the theme), and
    `extra_watched_files`: a change of any of them rebuilds it, and only it.
    """

    def __init__(
        self,
        input_dir: Path,
        output_dir: Path,
        assets_dir: Path,
        font_paths: Iterable[Path] = (),
        languages: Iterable[str] = ("fr", "en"),
        extra_watched_files: Iterable[Path] = (),
    ) -> None:
        """Initialize the builder.

        Args:
            input_dir: Directory holding the figures' `.typ` sources (and \
                any `_`-prefixed library they share), one SVG per figure \
                per language.
            output_dir: Directory the SVGs (and the mirrored sources) are \
                written to.
            assets_dir: Typst root every figure is compiled with, so it can \
                address other assets the way deck content does.
            font_paths: Extra font directories passed to the Typst compiler.
            languages: Languages each figure is compiled once per.
            extra_watched_files: Extra files whose change rebuilds every \
                figure, on top of those the figures reference.
        """
        self._input_dir = input_dir
        self._output_dir = output_dir
        self._assets_dir = assets_dir
        self._font_paths = tuple(str(path) for path in font_paths)
        self._languages = tuple(languages)
        self._extra_watched_files = tuple(extra_watched_files)
        self._logger = getLogger(__name__)

    def build_assets(self) -> None:
        sources = {
            path.relative_to(self._input_dir): path
            for suffix in ("*.typ", "*.yml")
            for path in self._input_dir.rglob(suffix)
        }
        for relative, source in sources.items():
            copy_file_if_changed(source, self._output_dir / relative)
        figures = [
            relative
            for relative in sources
            if relative.suffix == ".typ" and not relative.name.startswith("_")
        ]
        svgs = {
            self._svg_path(figure, lang): (figure, lang)
            for figure in figures
            for lang in self._languages
        }
        keep = {*svgs, *map(stamp_path, svgs)}
        for path in self._output_dir.rglob("*"):
            if (
                path.is_file()
                and path not in keep
                and path.relative_to(self._output_dir) not in sources
            ):
                path.unlink()

        to_build = []
        wrapper = self._typst_sources(self._input_dir / "_svg.typ")
        for svg, (figure, lang) in svgs.items():
            inputs = sorted(
                {
                    *self._typst_sources(self._input_dir / figure),
                    *wrapper,
                    *self._extra_watched_files,
                }
            )
            stamp = digest(inputs, lang)
            if not is_fresh(svg, stamp, inputs):
                to_build.append((svg, figure, lang, stamp))
        if not to_build:
            return
        self._logger.info("Compiling %d Typst figure(s) to SVG", len(to_build))
        from concurrent.futures import ThreadPoolExecutor

        # The typst bindings release the GIL while compiling: threads are enough.
        with ThreadPoolExecutor() as pool:
            failed = [
                error
                for error in pool.map(lambda item: self._compile(*item), to_build)
                if error
            ]
        if failed:
            msg = "failed to compile Typst figures to SVG:\n" + "\n".join(failed)
            raise DeckzError(msg)

    def watched_dirs(self) -> Iterable[Path]:
        return (self._input_dir,)

    def _typst_sources(self, file: Path) -> frozenset[Path]:
        """`file` and every file it references, transitively.

        A reference is any string literal naming an existing file, \
        relative to the referencing file or, starting with `/`, to \
        `assets_dir` (the Typst root, where `input_dir` is mirrored at \
        `output_dir`): imports, includes, images, data files, whatever \
        helper takes the path. A path built at run time (`"/img/" + name`) \
        isn't seen.

        Returns:
            The files, `.typ` sources under `input_dir` rather than their \
            mirrors.
        """
        found = {file}
        pending = [file]
        while pending:
            current = pending.pop()
            text = current.read_text(encoding="utf8", errors="replace")
            for reference in _STRING.findall(text):
                path = self._resolve(reference, current)
                if path is not None and path not in found:
                    found.add(path)
                    if path.suffix == ".typ":
                        pending.append(path)
        return frozenset(found)

    def _resolve(self, reference: str, current: Path) -> Path | None:
        if reference.startswith("/"):
            path = self._assets_dir / reference[1:]
            if path.is_relative_to(self._output_dir):
                path = self._input_dir / path.relative_to(self._output_dir)
        else:
            path = current.parent / reference
        try:
            return path if path.is_file() else None
        except OSError:  # E.g. a string too long to be a path.
            return None

    def _svg_path(self, figure: Path, lang: str) -> Path:
        return self._output_dir / figure.with_suffix(f".{lang}.svg")

    def _compile(self, svg: Path, figure: Path, lang: str, stamp: str) -> str | None:
        import typst

        try:
            svg.write_bytes(
                typst.compile(
                    str(self._output_dir / "_svg.typ"),
                    root=str(self._assets_dir),
                    font_paths=list(self._font_paths),
                    ignore_system_fonts=True,
                    format="svg",
                    sys_inputs={
                        "figure": f"/{self._output_dir.name}/{figure.as_posix()}",
                        "lang": lang,
                    },
                )
            )
        except typst.TypstError as error:
            return f"{figure} ({lang}):\n{error.diagnostic or error}"
        write_stamp(svg, stamp)
        return None
