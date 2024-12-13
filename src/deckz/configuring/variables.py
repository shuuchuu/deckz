from functools import reduce
from typing import Any

from ..utils import load_all_yamls
from .settings import DeckSettings


def get_variables(settings: DeckSettings) -> dict[str, Any]:
    return reduce(
        lambda a, b: {**a, **b},
        load_all_yamls(
            [
                settings.paths.session_variables,
                settings.paths.deck_variables,
                settings.paths.company_variables,
                settings.paths.user_variables,
                settings.paths.global_variables,
            ]
        ),
        {},
    )
