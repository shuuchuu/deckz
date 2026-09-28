from os import utime
from pathlib import Path

from deckz.utils import copy_file_if_changed


def test_copies_when_missing(tmp_path: Path) -> None:
    original = tmp_path / "a.md"
    original.write_text("a", encoding="utf8")
    copy = tmp_path / "build" / "a.md.j2"
    assert copy_file_if_changed(original, copy)
    assert copy.read_text(encoding="utf8") == "a"


def test_skips_same_content_even_if_original_is_newer(tmp_path: Path) -> None:
    original = tmp_path / "a.md"
    copy = tmp_path / "a.md.j2"
    copy.write_text("a", encoding="utf8")
    original.write_text("a", encoding="utf8")
    utime(copy, (0, 0))
    assert not copy_file_if_changed(original, copy)


def test_copies_changed_content_even_if_original_is_older(tmp_path: Path) -> None:
    # E.g. a `git checkout` restoring an older version of the file.
    original = tmp_path / "a.md"
    copy = tmp_path / "a.md.j2"
    original.write_text("old", encoding="utf8")
    copy.write_text("new", encoding="utf8")
    utime(original, (0, 0))
    assert copy_file_if_changed(original, copy)
    assert copy.read_text(encoding="utf8") == "old"
