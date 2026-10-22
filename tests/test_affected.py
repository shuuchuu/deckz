from pathlib import Path
from shutil import copytree
from typing import Any

from pytest import fixture

from deckz.analyzing.affected import deck_assets, deck_findings
from deckz.components.checks import Finding
from deckz.configuring.settings import DeckSettings


@fixture
def bilingual(tmp_path: Path, monkeypatch: Any) -> DeckSettings:
    import appdirs
    from pygit2 import init_repository

    root = tmp_path / "repo"
    copytree(Path(__file__).parent / "test_cli", root)
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    (root / "user-variables.yml").rename(user_dir / "variables.yml")
    monkeypatch.setattr(appdirs, "user_config_dir", lambda *_, **__: str(user_dir))
    init_repository(str(root))
    return DeckSettings.from_yaml(root / "company" / "bilingual")


def _show(path: Path, asset: str) -> None:
    path.write_text(f'Hello {{{{ assets_metadata_retriever("{asset}") }}}}\n')


def _credit(asset: str) -> Finding:
    return Finding(
        "asset-credits",
        f"assets/{asset}.yml:2: LaTeX in a credit line: write it in Markdown",
        blocking=False,
    )


def test_deck_assets_are_those_its_content_shows_in_either_language(
    bilingual: DeckSettings,
) -> None:
    content = bilingual.paths.current_dir / "content"
    _show(content / "hello.md", "img/logo")
    _show(content / "en" / "hello.md", "img/en-only")

    assets = bilingual.paths.assets_dir.resolve()
    assert deck_assets(bilingual) == {
        assets / "img" / "logo.yml",
        assets / "img" / "en-only.yml",
    }


def test_deck_findings_keeps_a_problem_in_an_asset_the_deck_shows(
    bilingual: DeckSettings,
) -> None:
    _show(bilingual.paths.current_dir / "content" / "hello.md", "img/logo")
    shown, other = _credit("img/logo"), _credit("img/other")
    image = Finding("image-size", "assets/img/logo.png: 4 MB", blocking=False)

    assert deck_findings(bilingual, [shown, other, image]) == [shown, image]


def test_deck_findings_renders_nothing_without_a_problem_in_an_asset(
    bilingual: DeckSettings, monkeypatch: Any
) -> None:
    from deckz.analyzing import affected

    def fail(_: DeckSettings) -> set[Path]:
        raise AssertionError

    monkeypatch.setattr(affected, "deck_assets", fail)
    mine = Finding("raw-latex", "company/bilingual/content/hello.md: x", False)

    assert deck_findings(bilingual, [mine]) == [mine]
