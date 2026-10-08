"""Options shared by several commands."""

from collections.abc import Iterable
from typing import Annotated

from cyclopts import Parameter

from ..models import Lang

Langs = Annotated[
    tuple[Lang, ...],
    Parameter(
        name="--lang",
        env_var="DECKZ_LANG",
        consume_multiple=True,
        negative="",
        show_default=lambda langs: " ".join(langs),
    ),
]
"""Languages to process in one pass: `--lang fr en`, or `--lang fr --lang en`.

Defaults to `DECKZ_LANG` (space-separated, e.g. `DECKZ_LANG="fr en"`, which a \
`.env` file can set) when the option isn't given. Commands that show a single \
resolved view take a plain `lang: Lang` instead, which ignores `DECKZ_LANG`.
"""


def unique(langs: Iterable[Lang]) -> tuple[Lang, ...]:
    """`langs` without repeats, in order.

    Returns:
        Each language once.
    """
    return tuple(dict.fromkeys(langs))
