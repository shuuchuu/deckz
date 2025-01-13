from pathlib import Path

from . import app


@app.command()
def tree(workdir: Path = Path()) -> None:
    """Show the WORKDIR's deck tree.

    Args:
        workdir: Path to move into before running the command.
    """
    from rich import print as rich_print

    from ..components.factory import DeckSettingsFactory
    from ..components.parser import RichTreeVisitor
    from ..configuring.settings import DeckSettings

    settings = DeckSettings.from_yaml(workdir)
    deck = (
        DeckSettingsFactory(settings)
        .parser()
        .from_deck_definition(settings.paths.deck_definition)
    )
    tree = RichTreeVisitor(only_errors=False).process(deck)
    rich_print(tree)
