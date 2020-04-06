from collections import ChainMap, OrderedDict
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Tuple

from click import prompt
from yaml import dump as yaml_dump, safe_load as yaml_safe_load

from deckz.paths import Paths


_logger = getLogger(__name__)


def get_config(paths: Paths) -> Dict[str, Any]:
    return OrderedDict(
        (k, v)
        for k, v in sorted(
            ChainMap(
                *[
                    _get_or_create_config(f, p)
                    for f, p in [
                        (_global_data, paths.global_config),
                        (_user_data, paths.user_config),
                        (_company_data, paths.company_config),
                        (_deck_data, paths.deck_config),
                        (_session_data, paths.session_config),
                    ]
                ],
            ).items()
        )
    )


def _get_or_create_config(
    data: Tuple[str, List[Tuple[str, str, str]]], path: Path
) -> Dict[str, Any]:
    name, prompts = data
    if not path.is_file():
        _create_config(name, prompts, path)
    with open(path, "r", encoding="utf8") as fh:
        return yaml_safe_load(fh)


def _create_config(name: str, prompts: List[Tuple[str, str, str]], path: Path) -> None:
    def _input(prompt_string: str, example: str) -> str:
        return prompt(
            f"Please enter {prompt_string}", default=example, show_default=True,
        )

    print("%s config not found. Let's create one." % name)
    config = {key: _input(prompt, example) for key, prompt, example in prompts}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf8") as fh:
        yaml_dump(config, fh)


_global_data = (
    "Global",
    [("presentation_size", "the size of the presentation", "10pt")],
)

_user_data = (
    "User",
    [
        ("trainer_name", "your full name", "John Doe"),
        ("trainer_email", "your professional email", "john.doe@gmail.com"),
        (
            "trainer_activity",
            "your professional activity",
            "Consultant/Formateur indépendant",
        ),
        (
            "trainer_specialization",
            "your professional specialization",
            "Intelligence Artificielle",
        ),
        (
            "trainer_training",
            "your formal training",
            "Master Intelligence Artificielle et Décision (Paris 6)",
        ),
    ],
)

_company_data = (
    "Company",
    [
        ("company_name", "the name of the company", "ORSYS"),
        ("company_logo", "the logo of the company", "logo_orsys"),
        ("company_logo_height", "the company logo height", "1cm"),
        ("company_website", "the website of the company", "https://www.orsys.fr/",),
    ],
)

_deck_data = (
    "Deck",
    [
        ("deck_title", "the title of the deck", "Big Data Analytics"),
        ("deck_acronym", "the acronym of the deck", "BDA"),
    ],
)

_session_data = (
    "Session",
    [
        (
            "session_start",
            "the start of the session in the format dd/mm/yyyy",
            "20/03/2020",
        ),
        (
            "session_end",
            "the end of the session in the format dd/mm/yyyy",
            "23/03/2020",
        ),
    ],
)
