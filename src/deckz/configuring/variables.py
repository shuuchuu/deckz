from functools import reduce
from typing import Any

from ..utils import load_all_yamls
from .settings import DeckSettings


def get_variables(settings: DeckSettings) -> dict[str, Any]:
    return reduce(
        lambda a, b: {**a, **b},
        load_all_yamls(
            [
                settings.paths.session_config,
                settings.paths.deck_config,
                settings.paths.company_config,
                settings.paths.user_config,
                settings.paths.global_config,
            ]
        ),
        {},
    )
