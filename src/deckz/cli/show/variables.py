from pathlib import Path

from ...models import Lang
from . import app


@app.command()
def variables(*, lang: Lang = "fr", json: bool = False, workdir: Path = Path()) -> None:
    """Print the resolved variables.

    Args:
        lang: Language to resolve translation maps to, as `deckz run` would
        json: Print them as one JSON object instead
        workdir: Path to move into before running the command

    """
    from rich import print as rich_print

    from ...configuring.settings import DeckSettings
    from ...configuring.variables import get_variables

    resolved = get_variables(DeckSettings.from_yaml(workdir), lang)
    if json:
        from .._presentation import print_json

        print_json(resolved)
        return
    max_length = max(len(key) for key in resolved)
    rich_print(
        "\n".join((f"[green]{k:{max_length}}[/] {v}") for k, v in resolved.items())
    )
