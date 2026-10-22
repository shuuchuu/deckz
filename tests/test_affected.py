from pathlib import Path
from shutil import copytree
from typing import Any

from pytest import fixture, raises

from deckz.analyzing.affected import affected_since, deck_assets, deck_findings
from deckz.cli import main
from deckz.components.checks import Finding
from deckz.configuring.settings import DeckSettings
from deckz.exceptions import DeckzError


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


def _commit_all(root: Path, message: str) -> None:
    import subprocess

    for args in (("add", "-A"), ("commit", "--quiet", "-m", message)):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
            cwd=root,
            check=True,
        )


def test_affected_since_counts_the_commits_and_the_working_tree(
    bilingual: DeckSettings, capsys: Any
) -> None:
    root = bilingual.paths.git_dir
    _commit_all(root, "Start")
    assert affected_since(root, "HEAD") == []

    hello = bilingual.paths.current_dir / "content" / "hello.md"
    hello.write_text("Changed\n")
    assert [d.paths.current_dir for d in affected_since(root, "HEAD")] == [
        bilingual.paths.current_dir
    ]
    _commit_all(root, "Change hello")
    main(("show", "affected", "--since", "HEAD~1", "--workdir", str(root)))
    assert capsys.readouterr().out == "company/bilingual\n"
    with raises(DeckzError, match="names no commit"):
        affected_since(root, "nope")


def test_run_decks_since_builds_nothing_when_no_deck_is_reached(
    bilingual: DeckSettings, monkeypatch: Any
) -> None:
    from deckz import pipelines

    def fail(*_: object, **__: object) -> None:
        raise AssertionError

    monkeypatch.setattr(pipelines, "build", fail)
    root = bilingual.paths.git_dir
    _commit_all(root, "Start")

    main(("run", "decks", "--since", "HEAD", "--workdir", str(root)))
