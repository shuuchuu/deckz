from collections import ChainMap
from logging import getLogger
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from appdirs import user_config_dir
from click import prompt
from yaml import dump as yaml_dump, safe_load as yaml_safe_load

from deckz import app_name
from deckz.utils import get_workdir_path


_logger = getLogger(__name__)


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


def _create_global_config(path: Path) -> None:
    _create_config(
        "Global", [("presentation_size", "the size of the presentation", "10pt")], path,
    )


def _create_user_config(path: Path) -> None:
    _create_config(
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
        path,
    )


def _create_company_config(path: Path) -> None:
    _create_config(
        "Company",
        [
            ("company_name", "the name of the company", "ORSYS"),
            ("company_logo", "the logo of the company", "logo_orsys"),
            ("company_logo_height", "the company logo height", "1cm"),
            ("company_website", "the website of the company", "https://www.orsys.fr/"),
        ],
        path,
    )


def _create_deck_config(path: Path) -> None:
    _create_config(
        "Deck",
        [
            ("deck_title", "the title of the deck", "Big Data Analytics"),
            ("deck_acronym", "the acronym of the deck", "BDA"),
        ],
        path,
    )


def _create_session_config(path: Path) -> None:
    _create_config(
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
        path,
    )


def _get_or_create_config(
    create_function: Callable[[Path], None], path: Path
) -> Dict[str, Any]:
    if not path.is_file():
        create_function(path)
    with open(path, "r", encoding="utf8") as fh:
        return yaml_safe_load(fh)


def _get_global_config() -> Dict[str, Any]:
    return _get_or_create_config(
        _create_global_config, get_workdir_path() / "global-config.yml"
    )


def _get_user_config() -> Dict[str, Any]:
    return _get_or_create_config(
        _create_user_config, Path(user_config_dir(app_name)) / "user-config.yml"
    )


def _get_company_config() -> Dict[str, Any]:
    return _get_or_create_config(
        _create_company_config, Path("..") / "company-config.yml"
    )


def _get_deck_config() -> Dict[str, Any]:
    return _get_or_create_config(_create_deck_config, Path("deck-config.yml"))


def _get_session_config() -> Dict[str, Any]:
    return _get_or_create_config(_create_session_config, Path("session-config.yml"))


def get_config() -> List[Tuple[str, Any]]:
    return [
        (k, v)
        for k, v in sorted(
            ChainMap(
                _get_global_config(),
                _get_user_config(),
                _get_company_config(),
                _get_deck_config(),
                _get_session_config(),
            ).items()
        )
    ]
