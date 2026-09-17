from pathlib import Path

from . import app


@app.command()
def tree(workdir: Path = Path(), *, paths: bool = False) -> None:
    """Show the WORKDIR's deck tree.

    Args:
        workdir: Path to move into before running the command.
        paths: Print the resolved absolute file paths instead, one per line, \
            sorted -- for scripting/scoping reads, not for human inspection.
    """
    from ..components.factory import DeckSettingsFactory
    from ..configuring.settings import DeckSettings

    settings = DeckSettings.from_yaml(workdir)
    deck = (
        DeckSettingsFactory(settings)
        .parser()
        .from_deck_definition(settings.paths.deck_definition)
    )

    if paths:
        from ..components.deck_builder import PartDependenciesNodeVisitor

        deps = PartDependenciesNodeVisitor().process(deck)
        resolved: set[Path] = set()
        for part_paths in deps.values():
            resolved.update(part_paths)
        for path in sorted(resolved):
            print(path)
        return

    from rich import print as rich_print

    from ..components.parser import RichTreeVisitor

    tree = RichTreeVisitor(only_errors=False).process(deck)
    rich_print(tree)
