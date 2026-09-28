from pathlib import Path

from . import app


@app.command()
@app.default
def tree(workdir: Path = Path(), *, en: bool = False, json: bool = False) -> None:
    """Show the WORKDIR's deck tree (default).

    Args:
        en: Resolve the English variant, as `deckz run --en` would
        json: Print the tree as one JSON object instead: the deck's "name"
            and "parts", each with its "name", "title" and nested "nodes"
            (with "kind", "path", "resolved_path", "title", "error", and for
            a section "flavor" and its own "nodes")
        workdir: Path to move into before running the command.
    """
    from rich import print as rich_print

    from ...components.factory import DeckSettingsFactory
    from ...configuring.settings import DeckSettings
    from .._presentation import RichTreeVisitor, deck_json, print_json

    settings = DeckSettings.from_yaml(workdir)
    deck = (
        DeckSettingsFactory(settings, lang="en" if en else "fr")
        .parser()
        .from_deck_definition(settings.paths.deck_definition)
    )

    if json:
        print_json(deck_json(deck))
        return
    tree = RichTreeVisitor(only_errors=False).process(deck)
    rich_print(tree)
