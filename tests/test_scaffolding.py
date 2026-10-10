from pathlib import Path
from shutil import copytree
from typing import Any

from pygit2 import init_repository
from pytest import fixture, raises

from deckz.analyzing.content_checks import lab_format, lab_ids, lab_pairs
from deckz.cli import main
from deckz.configuring.settings import GlobalSettings
from deckz.exceptions import ScaffoldRefusedError
from deckz.scaffolding import new_deck, new_lab, new_section


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    import appdirs

    root = tmp_path / "repo"
    copytree(Path(__file__).parent / "test_cli", root)
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    (root / "user-variables.yml").rename(user_dir / "variables.yml")
    monkeypatch.setattr(appdirs, "user_config_dir", lambda *_, **__: str(user_dir))
    init_repository(str(root))
    monkeypatch.chdir(root)
    return root


def _settings(repo: Path) -> GlobalSettings:
    return GlobalSettings.from_yaml(repo)


def test_new_lab_writes_a_pair_the_lab_checks_accept(repo: Path) -> None:
    created = new_lab(_settings(repo), "topic/word-count", "hands-on")

    assert [p.relative_to(repo).as_posix() for p in created.paths] == [
        "labs/notebooks/topic/word-count/hands-on-fr.ipynb",
        "labs/notebooks/topic/word-count/hands-on-en.ipynb",
    ]
    assert len(created.ids) == 2
    settings = _settings(repo)
    assert lab_pairs(settings) == []
    assert lab_format(settings) == []
    assert lab_ids(settings) == []


def test_new_lab_refuses_a_bad_kind_name_or_an_existing_lab(repo: Path) -> None:
    settings = _settings(repo)
    new_lab(settings, "topic/word-count", "demo")

    with raises(ScaffoldRefusedError, match="already exists"):
        new_lab(settings, "topic/word-count", "demo")
    with raises(ScaffoldRefusedError, match="hands-on or demo"):
        new_lab(settings, "topic/other", "exercise")
    with raises(ScaffoldRefusedError, match="lowercase"):
        new_lab(settings, "topic/Word_Count", "demo")


def test_new_section_compiles_in_both_languages(repo: Path) -> None:
    files = new_section(_settings(repo), "nlp/search", "Recherche")

    assert [f.relative_to(repo).as_posix() for f in files] == [
        "content/nlp/search/search.yml",
        "content/nlp/search/search.md",
        "content/nlp/search/en/search.md",
    ]
    main(
        (
            "run", "section", "nlp/search", "full", "--lang", "fr", "en",
            "--handout", "--no-presentation", "--no-print", "--no-open",
            # A deck's variables: the fixture's main template needs its logo.
            "--workdir", str(repo / "company" / "abc"),
        )
    )  # fmt: skip
    with raises(ScaffoldRefusedError):
        new_section(_settings(repo), "nlp/search")


def test_new_deck_parses(repo: Path, capsys: Any) -> None:
    new_deck(_settings(repo), repo / "company" / "new", "NEW", "Nouveau")

    main(("show", "tree", "--workdir", str(repo / "company" / "new")))

    assert capsys.readouterr().out == "NEW\n└── main\n"
    with raises(ScaffoldRefusedError):
        new_deck(_settings(repo), repo / "company" / "new", "NEW", "Nouveau")


def test_new_deck_renders_the_repository_template(repo: Path) -> None:
    template = repo / "templates" / "scaffold" / "deck"
    (template / "content" / "about").mkdir(parents=True)
    (template / "deck.yml.jinja").write_text(
        "name: {{ name }}\nparts:\n  - name: main\n    title: {{ title }}\n"
        "    sections: []\n",
        encoding="utf8",
    )
    (template / "content" / "about" / "description.md").write_text(
        "# {{ title }}\n", encoding="utf8"
    )

    files = new_deck(_settings(repo), repo / "company" / "new", "NEW", "Nouveau")

    assert sorted(f.relative_to(repo).as_posix() for f in files) == [
        "company/new/content/about/description.md",
        "company/new/deck.yml",
    ]
    description = repo / "company" / "new" / "content" / "about" / "description.md"
    assert description.read_text(encoding="utf8") == "# Nouveau\n"
