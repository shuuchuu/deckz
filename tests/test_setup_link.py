from pathlib import Path

from pytest import raises

from deckz.components.deck_builder import setup_link
from deckz.exceptions import DeckzError


def test_setup_link_creates_link(tmp_path: Path) -> None:
    target = tmp_path / "assets" / "img"
    target.mkdir(parents=True)
    source = tmp_path / "build" / "img"
    setup_link(source, target)
    assert source.resolve() == target.resolve()


def test_setup_link_relinks_dangling_link(tmp_path: Path) -> None:
    target = tmp_path / "assets" / "img"
    target.mkdir(parents=True)
    source = tmp_path / "build" / "img"
    source.parent.mkdir()
    source.symlink_to(tmp_path / "shared" / "img")
    setup_link(source, target)
    assert source.resolve() == target.resolve()


def test_setup_link_relinks_link_to_other_target(tmp_path: Path) -> None:
    target = tmp_path / "assets" / "img"
    target.mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    source = tmp_path / "build" / "img"
    source.parent.mkdir()
    source.symlink_to(other)
    setup_link(source, target)
    assert source.resolve() == target.resolve()


def test_setup_link_refuses_to_replace_a_real_directory(tmp_path: Path) -> None:
    target = tmp_path / "assets" / "img"
    target.mkdir(parents=True)
    source = tmp_path / "build" / "img"
    source.mkdir(parents=True)
    with raises(DeckzError):
        setup_link(source, target)
