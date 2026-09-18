from pathlib import Path
from typing import Any
from unittest.mock import patch

from pytest import fixture

from deckz.cli import main
from deckz.utils import load_yaml


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")


def run_deckz(*args: str) -> None:
    with patch("sys.argv", ["deckz", *args]):
        try:
            main()
        except SystemExit as e:
            if e.code != 0:
                raise e


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    import appdirs
    from pygit2 import init_repository

    init_repository(str(tmp_path))
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_path))
    monkeypatch.chdir(tmp_path)
    _write(
        tmp_path / "deckz.yml", 'build_command: ["true"]\nfile_extensions: [".md"]\n'
    )

    shared = tmp_path / "shared" / "latex"
    _write(
        shared / "greeting" / "greeting.yml",
        "title: Greeting\n"
        "flavors:\n"
        "  - name: casual\n"
        "    includes:\n"
        "      - hello\n"
        "  - name: formal\n"
        "    includes:\n"
        "      - hello\n",
    )
    _write(shared / "greeting" / "hello.md", "# Hello\n\nHi!\n")

    _write(
        tmp_path / "company" / "xyz" / "deck.yml",
        "name: XYZ\n"
        "parts:\n"
        "  - name: p1\n"
        "    title: Part 1\n"
        "    sections:\n"
        "      - $greeting@casual\n"
        "      - $greeting@formal\n",
    )
    return tmp_path


def test_flavor_deduplicate_merges_identical_flavors_with_markdown_content(
    repo: Path,
) -> None:
    run_deckz("flavor", "deduplicate")

    section_data = load_yaml(repo / "shared" / "latex" / "greeting" / "greeting.yml")
    flavor_names = [flavor["name"] for flavor in section_data["flavors"]]
    assert flavor_names == ["casual"]

    deck_data = load_yaml(repo / "company" / "xyz" / "deck.yml")
    assert deck_data["parts"][0]["sections"] == ["$greeting@casual", "$greeting@casual"]

    # The Markdown content file itself is untouched: deduplication only ever
    # rewrites yaml, never file bodies.
    assert (repo / "shared" / "latex" / "greeting" / "hello.md").read_text(
        encoding="utf8"
    ) == "# Hello\n\nHi!\n"


def test_flavor_rename_rewrites_usages_with_markdown_content(repo: Path) -> None:
    run_deckz("flavor", "rename", "greeting", "casual", "friendly")

    section_data = load_yaml(repo / "shared" / "latex" / "greeting" / "greeting.yml")
    flavor_names = [flavor["name"] for flavor in section_data["flavors"]]
    assert flavor_names == ["friendly", "formal"]

    deck_data = load_yaml(repo / "company" / "xyz" / "deck.yml")
    assert deck_data["parts"][0]["sections"] == [
        "$greeting@friendly",
        "$greeting@formal",
    ]
