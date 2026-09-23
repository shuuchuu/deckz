from pathlib import Path
from shutil import copytree
from typing import Any

import appdirs
from pygit2 import init_repository

from deckz.utils import all_deck_settings


def test_all_deck_settings_skips_build_directories(
    tmp_path: Path, monkeypatch: Any
) -> None:
    git_dir = tmp_path / "data"
    copytree(Path(__file__).parent / "test_cli_typst", git_dir)
    init_repository(str(git_dir))
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(user_dir))
    deck_dir = git_dir / "company" / "abc"
    stale = deck_dir / ".build" / "old-harness"
    stale.mkdir(parents=True)
    (stale / "deck.yml").symlink_to(deck_dir / "deck.yml")
    assert [s.paths.current_dir for s in all_deck_settings(git_dir)] == [deck_dir]
