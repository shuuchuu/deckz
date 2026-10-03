"""Package an HTML deck: the page plus every local file it references.

The HTML counterpart of compiling a PDF. A deck's main HTML page is rendered \
in its build directory, where the target repository's assets are linked \
(`img/`, `fonts/`, ...), so it can reference them relatively. Packaging \
copies the page, as `index.html`, and every file it references into a \
self-contained `<name>.site/` directory next to it, which the deck builder \
then publishes. References are found in the page's attributes (`src`, \
`href`, `poster`, ...), in its `style` attributes and `<style>` blocks, and in \
referenced CSS files (`url(...)`, `@import`), recursively. Files loaded by \
scripts (e.g. a math renderer's fonts) can't be found that way: \
`static_dirs` names directories to copy whole instead.

A reference that doesn't resolve to a file under the build directory fails \
the packaging rather than shipping a broken page. URLs with a scheme \
(`https:`, `data:`, `mailto:`, ...) and in-page anchors are left alone.
"""

import re
from collections.abc import Iterable, Iterator
from html.parser import HTMLParser
from os import walk
from pathlib import Path, PurePosixPath
from posixpath import normpath
from urllib.parse import unquote, urlsplit

from ..models import CompileResult
from ..utils import sync_tree
from .protocols import CompilerProtocol

_URL_ATTRIBUTES = frozenset(
    {
        "src",
        "data-src",
        "href",
        "poster",
        "data-poster",
        "data-background-image",
        "data-background-video",
        "data-background-iframe",
    }
)
_SRCSET_ATTRIBUTES = frozenset({"srcset", "data-srcset"})
_CSS_URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""")
_CSS_IMPORT = re.compile(r"""@import\s+(['"])(.*?)\1""")


class _ReferencesParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._in_style = tag == "style"
        for name, value in attrs:
            if value is None:
                continue
            if name in _URL_ATTRIBUTES:
                self.references.append(value)
            elif name in _SRCSET_ATTRIBUTES:
                self.references.extend(
                    candidate.split()[0]
                    for candidate in value.split(",")
                    if candidate.strip()
                )
            elif name == "style":
                self.references.extend(_css_references(value))

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.references.extend(_css_references(data))


def _css_references(css: str) -> Iterator[str]:
    for match in _CSS_URL.finditer(css):
        yield match.group(2)
    for match in _CSS_IMPORT.finditer(css):
        yield match.group(2)


def _resolve(
    referrer: PurePosixPath | None, reference: str
) -> PurePosixPath | str | None:
    """Where a reference points to, relative to the build directory.

    Args:
        referrer: File the reference is in, relative to the build directory, \
            or `None` for the page itself.
        reference: The reference, as written.

    Returns:
        The path of the file, `None` for a reference to leave alone (a URL \
        or an in-page anchor), or an error message.
    """
    reference = reference.strip()
    parts = urlsplit(reference)
    if not reference or reference.startswith("#") or parts.scheme or parts.netloc:
        return None
    local = unquote(parts.path)
    if not local:
        return None
    label = "index.html" if referrer is None else referrer.as_posix()
    if local.startswith("/"):
        return (
            f"{label}: {reference!r} is root-absolute, only relative references "
            "can be packaged"
        )
    base = PurePosixPath() if referrer is None else referrer.parent
    relative = normpath((base / local).as_posix())
    if relative == ".." or relative.startswith("../"):
        return f"{label}: {reference!r} points outside the build directory"
    return PurePosixPath(relative)


class HtmlPackager(CompilerProtocol):
    def __init__(self, static_dirs: Iterable[str] = ()) -> None:
        self._static_dirs = tuple(static_dirs)

    def compile(self, file: Path) -> CompileResult:
        root = file.parent
        files: dict[PurePosixPath, Path] = {PurePosixPath("index.html"): file}
        errors: list[str] = []
        self._add_static_dirs(root, files, errors)

        parser = _ReferencesParser()
        parser.feed(file.read_text(encoding="utf8"))
        parser.close()
        pending: list[tuple[PurePosixPath | None, str]] = [
            (None, reference) for reference in parser.references
        ]
        # Stylesheets a static dir brings in: what they reference may live
        # elsewhere (e.g. fonts).
        scanned = {path for path in files if path.suffix == ".css"}
        for path in scanned:
            css = files[path].read_text(encoding="utf8")
            pending.extend((path, found) for found in _css_references(css))
        while pending:
            referrer, reference = pending.pop()
            resolved = _resolve(referrer, reference)
            if resolved is None:
                continue
            if isinstance(resolved, str):
                errors.append(resolved)
                continue
            source = root / resolved
            if resolved not in files:
                if not source.is_file():
                    label = "index.html" if referrer is None else referrer.as_posix()
                    errors.append(f"{label}: {reference!r} not found")
                    continue
                files[resolved] = source
            if source.suffix == ".css" and resolved not in scanned:
                scanned.add(resolved)
                css = source.read_text(encoding="utf8")
                pending.extend((resolved, found) for found in _css_references(css))

        if errors:
            return CompileResult(ok=False, diagnostics="\n".join(sorted(errors)))
        sync_tree(files, file.with_suffix(".site"))
        return CompileResult(ok=True)

    def _add_static_dirs(
        self, root: Path, files: dict[PurePosixPath, Path], errors: list[str]
    ) -> None:
        for static_dir in self._static_dirs:
            directory = root / static_dir
            if not directory.is_dir():
                errors.append(f"static directory {static_dir!r} not found in {root}")
                continue
            # Asset directories are symlinked into the build dir: follow them.
            for dirpath, _, filenames in walk(directory, followlinks=True):
                for filename in filenames:
                    path = Path(dirpath) / filename
                    files[PurePosixPath(path.relative_to(root).as_posix())] = path
