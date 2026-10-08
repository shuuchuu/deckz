from pathlib import Path

from ...models import Lang
from . import app


@app.command()
def paths(*, lang: Lang = "fr", json: bool = False, workdir: Path = Path()) -> None:
    """Print the resolved absolute file paths of the WORKDIR's deck tree.

    One path per line, sorted -- for scripting/scoping reads, not for human
    inspection.

    Args:
        lang: Language to resolve the deck in, as `deckz run` would
        json: Print one JSON array of paths instead
        workdir: Path to move into before running the command
    """
    from ...components.deck_builder import PartDependenciesNodeVisitor
    from ...components.factory import DeckSettingsFactory
    from ...configuring.settings import DeckSettings

    settings = DeckSettings.from_yaml(workdir)
    deck = (
        DeckSettingsFactory(settings, lang=lang)
        .parser()
        .from_deck_definition(settings.paths.deck_definition)
    )

    deps = PartDependenciesNodeVisitor().process(deck)
    resolved: set[Path] = set()
    for part_deps in deps.values():
        resolved.update(dependency.resolved_path for dependency in part_deps)
    if json:
        from .._presentation import print_json

        print_json(sorted(resolved))
        return
    for path in sorted(resolved):
        print(path)
