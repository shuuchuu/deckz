from os import environ
from pathlib import Path
from typing import Any

import appdirs
from pytest import fixture


@fixture(autouse=True)
def _isolated_user_config_dir(tmp_path: Path, monkeypatch: Any) -> None:
    # Never read or write the developer's own ~/.config/deckz. Tests needing
    # specific user config patch this again with their own directory.
    user_dir = tmp_path / "isolated-user-config"
    monkeypatch.setattr(appdirs, "user_config_dir", lambda *_, **__: str(user_dir))


@fixture(autouse=True)
def _isolated_environment(monkeypatch: Any) -> None:
    # Neither the developer's own DECKZ_* defaults (e.g. DECKZ_LANG) nor a
    # .env file above the test's directory may change what a command does.
    for name in [name for name in environ if name.startswith("DECKZ_")]:
        monkeypatch.delenv(name)
    monkeypatch.setattr("dotenv.find_dotenv", lambda *_, **__: "")
