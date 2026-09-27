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
