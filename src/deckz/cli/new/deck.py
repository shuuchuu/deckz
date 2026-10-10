from pathlib import Path

from . import app


@app.command()
def deck(directory: Path, /, *, name: str, title: str) -> None:
    """Create a deck in DIRECTORY.

    From the repository's `templates/scaffold/deck/` (each file rendered with
    Jinja, `{{ name }}` and `{{ title }}`), else a `deck.yml` with one empty
    part. Refuses if DIRECTORY already holds a deck. Then list its sections
    in `deck.yml` (`deckz search-sections` finds them) and build it.

    Args:
        directory: The new deck's directory, e.g. `company/CODE`
        name: The deck's name, which its PDFs are named after
        title: The deck's title
    """
    from ...configuring.settings import GlobalSettings
    from ...scaffolding import new_deck

    settings = GlobalSettings.from_yaml(Path())
    for path in new_deck(settings, directory, name, title):
        print(path.relative_to(settings.paths.git_dir))
