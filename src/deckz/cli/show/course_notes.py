from pathlib import Path
from typing import TYPE_CHECKING

from ...models import Lang
from . import app

if TYPE_CHECKING:
    from ...course_notes import ChapterEntry, Coverage


@app.command(name="course-notes")
def course_notes(
    *, lang: Lang = "fr", json: bool = False, workdir: Path = Path()
) -> None:
    """Print each content file of the WORKDIR's deck with its course notes chapter.

    In the deck's order, each file once: `written` (its own chapter),
    `covered` (another file's chapter covers it, `course_notes.same_as`),
    `skipped` (no chapter on purpose, `course_notes.skip`) or `missing`,
    then the chapter's path. `deckz run course-notes` compiles the written ones.

    Outside a deck (WORKDIR holds no `deck.yml`, e.g. the repository's root or a
    catalog), every deck under WORKDIR instead: its counts per status and the
    share of its files needing a chapter that have one, then the same over the
    distinct content files of those decks.

    Args:
        lang: Language of the chapters, as `deckz run course-notes` would build them
        json: Print JSON instead: for a deck, one array of {path, status, chapter};
            outside one, {decks: [{deck, counts, share, error, entries}], files:
            [{path, status, chapter}], counts, share}
        workdir: Path to move into before running the command
    """
    if not (workdir / "deck.yml").is_file():
        _repository(workdir, lang=lang, json=json)
        return

    from ...components.factory import DeckSettingsFactory
    from ...configuring.settings import DeckSettings
    from ...course_notes import entries

    settings = DeckSettings.from_yaml(workdir)
    deck = (
        DeckSettingsFactory(settings, lang=lang)
        .parser()
        .from_deck_definition(settings.paths.deck_definition)
    )
    found = entries(settings, deck, lang)
    git_dir = settings.paths.git_dir
    if json:
        from .._presentation import print_json

        print_json([_entry_json(entry, git_dir) for entry in found])
        return
    for entry in found:
        chapter = entry.chapter.relative_to(git_dir)
        print(f"{entry.status.value:<8} {entry.path}  ({chapter})")


def _repository(workdir: Path, *, lang: Lang, json: bool) -> None:
    from ...configuring.settings import GlobalSettings
    from ...course_notes import repository_coverage
    from ...exceptions import CourseNotesError

    settings = GlobalSettings.from_yaml(workdir)
    coverage = repository_coverage(settings, workdir, lang)
    if not coverage.decks:
        msg = (
            f"no deck under {workdir.resolve()}: run `deckz show course-notes` from "
            "a deck's directory, or from a directory holding decks (e.g. the "
            "repository's root), or pass it as --workdir"
        )
        raise CourseNotesError(msg)
    if json:
        _print_coverage_json(coverage, settings.paths.git_dir)
    else:
        _print_coverage(coverage)


def _counts(found: "tuple[ChapterEntry, ...]") -> dict[str, int]:
    from ...course_notes import ChapterStatus

    return {
        status.value: sum(e.status is status for e in found) for status in ChapterStatus
    }


def _share_text(share: float | None) -> str:
    return "no file needs a chapter" if share is None else f"{share:.0%} with a chapter"


def _counts_text(counts: dict[str, int]) -> str:
    return ", ".join(f"{n} {status}" for status, n in counts.items())


def _print_coverage(coverage: "Coverage") -> None:
    from ...course_notes import coverage_share

    width = max(len(deck.deck) for deck in coverage.decks)
    for deck in coverage.decks:
        if deck.error is not None:
            print(f"{deck.deck:<{width}}  doesn't parse: {deck.error}")
            continue
        share = _share_text(coverage_share(deck.entries))
        print(f"{deck.deck:<{width}}  {_counts_text(_counts(deck.entries))}: {share}")
    files = coverage.files
    print(
        f"\n{len(files)} distinct content files: {_counts_text(_counts(files))}: "
        f"{_share_text(coverage_share(files))}"
    )


def _entry_json(entry: "ChapterEntry", git_dir: Path) -> dict[str, object]:
    return {
        "path": entry.path,
        "status": entry.status.value,
        "chapter": entry.chapter.relative_to(git_dir),
    }


def _print_coverage_json(coverage: "Coverage", git_dir: Path) -> None:
    from ...course_notes import coverage_share
    from .._presentation import print_json

    print_json(
        {
            "decks": [
                {
                    "deck": deck.deck,
                    "counts": _counts(deck.entries),
                    "share": coverage_share(deck.entries),
                    "error": deck.error,
                    "entries": [_entry_json(e, git_dir) for e in deck.entries],
                }
                for deck in coverage.decks
            ],
            "files": [_entry_json(e, git_dir) for e in coverage.files],
            "counts": _counts(coverage.files),
            "share": coverage_share(coverage.files),
        }
    )
