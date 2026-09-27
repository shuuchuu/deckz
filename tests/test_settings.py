from pathlib import Path
from shutil import copytree
from typing import Any

import appdirs
from pydantic import ValidationError
from pygit2 import init_repository
from pytest import raises

from deckz.configuring.settings import DeckSettings


def _deck_dir(tmp_path: Path) -> Path:
    git_dir = tmp_path / "data"
    copytree(Path(__file__).parent / "test_cli_typst", git_dir)
    init_repository(str(git_dir))
    return git_dir / "company" / "abc"


def test_loading_settings_does_not_create_the_user_config_dir(
    tmp_path: Path, monkeypatch: Any
) -> None:
    user_dir = tmp_path / "user"
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(user_dir))
    settings = DeckSettings.from_yaml(_deck_dir(tmp_path))
    assert settings.paths.user_config_dir == user_dir.resolve()
    assert not user_dir.exists()


def test_settings_are_frozen(tmp_path: Path) -> None:
    settings = DeckSettings.from_yaml(_deck_dir(tmp_path))
    with raises(ValidationError):
        settings.paths.pdf_dir = tmp_path  # ty: ignore[invalid-assignment]
    with raises(ValidationError):
        settings.file_extensions = (".typ",)  # ty: ignore[invalid-assignment]


def test_with_output_dirs_leaves_the_original_untouched(tmp_path: Path) -> None:
    settings = DeckSettings.from_yaml(_deck_dir(tmp_path))
    copy = settings.with_output_dirs(tmp_path / "build", tmp_path / "pdf")
    assert copy.paths.pdf_dir == tmp_path / "pdf"
    assert settings.paths.pdf_dir != tmp_path / "pdf"
