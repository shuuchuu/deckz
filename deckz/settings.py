from yaml import safe_load

from deckz.exceptions import DeckzException
from deckz.paths import GlobalPaths


class Settings:
    def __init__(self, global_paths: GlobalPaths):
        if not global_paths.settings.is_file():
            raise DeckzException(
                f"Could not find settings file at {global_paths.settings}."
            )
        with global_paths.settings.open(encoding="utf8") as fh:
            settings = safe_load(fh)
        if "build_command" not in settings:
            raise DeckzException(
                f"Could not find “build_command” key in {global_paths.settings}."
            )
        self.build_command = settings["build_command"]
