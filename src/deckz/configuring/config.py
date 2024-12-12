from collections import ChainMap
from pathlib import Path
from shutil import copy as shutil_copy
from typing import Any

from yaml import safe_load

from ..exceptions import DeckzError
from .settings import DeckSettings


def get_config(settings: DeckSettings) -> dict[str, Any]:
    return dict(
        sorted(
            ChainMap(
                *(
                    _get_or_create_config(config_path, template_path)
                    for config_path, template_path in [
                        (settings.paths.session_config, None),
                        (
                            settings.paths.deck_config,
                            settings.paths.template_deck_config,
                        ),
                        (
                            settings.paths.company_config,
                            settings.paths.template_company_config,
                        ),
                        (
                            settings.paths.user_config,
                            settings.paths.template_user_config,
                        ),
                        (
                            settings.paths.global_config,
                            settings.paths.template_global_config,
                        ),
                    ]
                ),
            ).items()
        )
    )


def _get_or_create_config(
    config_path: Path, template_path: Path | None
) -> dict[str, Any]:
    if not config_path.is_file():
        if template_path:
            if template_path.is_file():
                shutil_copy(str(template_path), str(config_path), follow_symlinks=True)
                msg = (
                    f"{config_path} was not found, copied {template_path} there. "
                    "Please edit it"
                )
                raise DeckzError(msg)
            msg = (
                f"neither {config_path} nor {template_path} were found. "
                "Please create both"
            )
            raise DeckzError(msg)
        return {}

    return safe_load(config_path.read_text(encoding="utf8"))
