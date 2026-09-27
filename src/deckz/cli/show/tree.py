from pathlib import Path

from . import app


@app.command()
@app.default
def tree(workdir: Path = Path(), *, en: bool = False) -> None:
    """Show the WORKDIR's deck tree (default).

    Args:
        en: Resolve the English variant, as `deckz run --en` would
        workdir: Path to move into before running the command.
    """
    from rich import print as rich_print

    from ...components.factory import DeckSettingsFactory
    from ...configuring.settings import DeckSettings
    from .._presentation import RichTreeVisitor

    settings = DeckSettings.from_yaml(workdir)
    deck = (
        DeckSettingsFactory(settings, lang="en" if en else "fr")
        .parser()
        .from_deck_definition(settings.paths.deck_definition)
    )

    tree = RichTreeVisitor(only_errors=False).process(deck)
    rich_print(tree)
