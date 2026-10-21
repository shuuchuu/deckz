from pathlib import Path

from ...models import Lang
from . import app


@app.command(name="course-notes")
def course_notes(
    *, lang: Lang = "fr", json: bool = False, workdir: Path = Path()
) -> None:
    """Print each content file of the WORKDIR's deck with its course notes chapter.

    In the deck's order, each file once: `written` (its own chapter),
    `covered` (another file's chapter covers it, `course_notes.same_as`),
    `skipped` (no chapter on purpose, `course_notes.skip`) or `missing`,
    then the chapter's path. `deckz run course-notes` compiles the written ones.

    Args:
        lang: Language of the chapters, as `deckz run course-notes` would build them
        json: Print one JSON array of {path, status, chapter} instead
        workdir: Path to move into before running the command
    """
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

        print_json(
            [
                {
                    "path": entry.path,
                    "status": entry.status.value,
                    "chapter": entry.chapter.relative_to(git_dir),
                }
                for entry in found
            ]
        )
        return
    for entry in found:
        chapter = entry.chapter.relative_to(git_dir)
        print(f"{entry.status.value:<8} {entry.path}  ({chapter})")
