"""A deck's course notes: its written-out reference, one chapter per content file.

The chapter of `<content_dir>/<path>.md` is `<course_notes_dir>/<path>.md` (in
English, `<course_notes_dir>/<dir>/en/<name>.md`, like content's), in the same
Markdown as the slides. A chapter is shared like the content file it writes out:
every deck including that file gets it in its course notes. `deckz.yml`'s
`course_notes` lists the content files with no chapter of their own (`skip`) and
those another file's chapter covers (`same_as`).

A deck's course notes are its own tree (`chapters_deck`): its parts and sections,
each content file replaced by its chapter (once, where it first comes), without the
files that have none. `pipelines.course_notes_targets` builds that tree through the
deck builder's `CourseNotes` output, with `paths.jinja2_course_notes_main_template`.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from .models import (
    Deck,
    File,
    Lang,
    Node,
    Part,
    ResolvedPath,
    Section,
    UnresolvedPath,
)

if TYPE_CHECKING:
    from .configuring.settings import GlobalSettings


class ChapterStatus(Enum):
    WRITTEN = "written"
    """The file has its own chapter."""
    COVERED = "covered"
    """Another file's chapter covers it (`same_as`), and it's written."""
    SKIPPED = "skipped"
    """The file has no chapter, on purpose (`skip`)."""
    MISSING = "missing"
    """The chapter that would cover it isn't written yet."""


@dataclass(frozen=True)
class ChapterEntry:
    """A content file of a deck, and the chapter writing it out."""

    path: str
    """The content file, relative to the content directory, without extension."""
    chapter: Path
    """The chapter covering it, written or not."""
    status: ChapterStatus


def _extension(settings: "GlobalSettings") -> str:
    return settings.file_extensions[0] if settings.file_extensions else ".md"


def chapter_path(settings: "GlobalSettings", path: str, lang: Lang) -> Path:
    """The chapter writing out the content file `path`, in `lang`.

    Args:
        settings: The repository's settings.
        path: The content file, relative to the content directory, without \
            extension.
        lang: The chapter's language.

    Returns:
        Its path in the course notes directory, whether it exists or not.
    """
    file = PurePosixPath(path)
    directory = settings.paths.course_notes_dir / file.parent
    if lang == "en":
        directory /= "en"
    return directory / f"{file.name}{_extension(settings)}"


def covering(settings: "GlobalSettings", path: str) -> str:
    """The content file whose chapter covers `path`.

    Returns:
        `path` itself, unless `course_notes.same_as` names another.
    """
    return settings.course_notes.same_as.get(path, path)


def skipped(settings: "GlobalSettings", path: str) -> bool:
    """Whether `path` has no chapter on purpose (`course_notes.skip`).

    Returns:
        True if one of the patterns matches it.
    """
    return any(
        PurePosixPath(path).full_match(pattern)
        for pattern in settings.course_notes.skip
    )


def entry(settings: "GlobalSettings", path: str, lang: Lang) -> ChapterEntry:
    """The chapter of the content file `path`, and whether it's written.

    Returns:
        The entry.
    """
    target = covering(settings, path)
    chapter = chapter_path(settings, target, lang)
    if chapter.is_file():
        status = ChapterStatus.WRITTEN if target == path else ChapterStatus.COVERED
    elif skipped(settings, path):
        status = ChapterStatus.SKIPPED
    else:
        status = ChapterStatus.MISSING
    return ChapterEntry(path, chapter, status)


def _files(nodes: Iterable[Node]) -> Iterator[File]:
    for node in nodes:
        if isinstance(node, Section):
            yield from _files(node.nodes)
        elif isinstance(node, File):
            yield node


def entries(settings: "GlobalSettings", deck: Deck, lang: Lang) -> list[ChapterEntry]:
    """The deck's content files, in order, each once, with their chapter.

    Returns:
        One entry per file.
    """
    paths = dict.fromkeys(
        str(file.unresolved_path)
        for part in deck.parts.values()
        for file in _files(part.nodes)
    )
    return [entry(settings, path, lang) for path in paths]


def chapters_deck(settings: "GlobalSettings", deck: Deck, lang: Lang) -> Deck:
    """`deck`, each content file replaced by its chapter.

    A chapter comes once, where the first file it covers comes. The files \
    with no chapter written are left out, and so are the sections and parts \
    they leave empty.

    Returns:
        The course notes' tree, named like `deck`.
    """
    seen: set[str] = set()

    def chapter(node: Node) -> Node | None:
        if isinstance(node, Section):
            nodes = tuple(n for n in map(chapter, node.nodes) if n is not None)
            return replace(node, nodes=nodes) if nodes else None
        target = covering(settings, str(node.unresolved_path))
        path = chapter_path(settings, target, lang)
        if target in seen or not path.is_file():
            return None
        seen.add(target)
        return replace(
            node,
            unresolved_path=UnresolvedPath(PurePosixPath(target)),
            resolved_path=ResolvedPath(path.resolve()),
        )

    parts = {}
    for name, part in deck.parts.items():
        nodes = tuple(n for n in map(chapter, part.nodes) if n is not None)
        if nodes:
            parts[name] = Part(title=part.title, nodes=nodes)
    return Deck(name=deck.name, parts=parts)


def chapters(settings: "GlobalSettings") -> Iterator[tuple[str, Lang]]:
    """Every chapter of the course notes directory.

    Yields:
        The content file it writes out (relative to the content directory, \
        without extension) and its language.
    """
    root = settings.paths.course_notes_dir
    if not root.is_dir():
        return
    extension = _extension(settings)
    for path in sorted(root.rglob(f"*{extension}")):
        rel = PurePosixPath(path.relative_to(root).as_posix())
        name = rel.name.removesuffix(extension)
        if rel.parent.name == "en":
            yield str(rel.parent.parent / name), "en"
        else:
            yield str(rel.parent / name), "fr"


def course_notes_pairs(
    settings: "GlobalSettings",
) -> Iterator[tuple[PurePosixPath, PurePosixPath]]:
    """Every chapter's fr/en pair, as paths relative to the git root.

    Yields:
        Each pair, French side first, whichever sides exist.
    """
    git_dir = settings.paths.git_dir
    seen: set[str] = set()
    for path, _ in chapters(settings):
        if path in seen:
            continue
        seen.add(path)
        fr, en = (
            PurePosixPath(chapter_path(settings, path, lang).relative_to(git_dir))
            for lang in ("fr", "en")
        )
        yield fr, en
