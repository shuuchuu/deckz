from typing import List

from pydantic import BaseModel
from yaml import safe_load

from deckz.exceptions import DeckzException
from deckz.paths import GlobalPaths


class Settings(BaseModel):

    build_command: List[str]

    @classmethod
    def from_global_paths(cls, global_paths: GlobalPaths) -> "Settings":
        if not global_paths.settings.is_file():
            raise DeckzException(
                f"Could not find settings file at {global_paths.settings}."
            )
        return cls.parse_obj(
            safe_load(global_paths.settings.read_text(encoding="utf8"))
        )
