from pathlib import Path
from typing import Any

from pytest import fixture

from deckz.analyzing.i18n_analyzer import (
    deck_pair,
    section_en_leak,
    section_files,
    section_flavor_diff,
    section_pair,
)
from deckz.configuring.settings import DeckSettings, GlobalSettings
from deckz.models import FlavorName


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")


def _heading(title: str) -> str:
    return f"# {title}\n\n{title}!\n"


def _frame(title: str) -> str:
    return f"\\begin{{frame}}{{{title}}}\n  {title}!\n\\end{{frame}}\n"


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    import appdirs
    from pygit2 import init_repository

    init_repository(str(tmp_path))
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_path))
    _write(
        tmp_path / "deckz.yml",
        'build_command: ["true"]\nfile_extensions: [".md", ".tex"]\n',
    )

    shared = tmp_path / "shared" / "latex"

    # A section already migrated to Markdown.
    _write(
        shared / "i18n-demo" / "i18n-demo.yml",
        "title: I18n demo section\n"
        "default_titles:\n"
        "  hello: Bonjour\n"
        "flavors:\n"
        "  - name: hello\n"
        "    includes:\n"
        "      - hello\n",
    )
    _write(shared / "i18n-demo" / "hello.md", _heading("Bonjour"))
    _write(
        shared / "i18n-demo" / "en" / "en.yml",
        "title: I18n demo section (en)\n"
        "default_titles:\n"
        "  hello: Hello\n"
        "flavors:\n"
        "  - name: hello\n"
        "    includes:\n"
        "      - hello\n",
    )
    _write(shared / "i18n-demo" / "en" / "hello.md", _heading("Hello"))

    # A section still in legacy LaTeX, coexisting in the same repo/settings.
    _write(
        shared / "i18n-demo-legacy" / "i18n-demo-legacy.yml",
        "title: I18n demo section (legacy)\n"
        "default_titles:\n"
        "  goodbye: Au revoir\n"
        "flavors:\n"
        "  - name: goodbye\n"
        "    includes:\n"
        "      - goodbye\n",
    )
    _write(shared / "i18n-demo-legacy" / "goodbye.tex", _frame("Au revoir"))
    _write(
        shared / "i18n-demo-legacy" / "en" / "en.yml",
        "title: I18n demo section (legacy, en)\n"
        "default_titles:\n"
        "  goodbye: Goodbye\n"
        "flavors:\n"
        "  - name: goodbye\n"
        "    includes:\n"
        "      - goodbye\n",
    )
    _write(shared / "i18n-demo-legacy" / "en" / "goodbye.tex", _frame("Goodbye"))

    # A section whose fr side was just migrated to Markdown, but whose en
    # side hasn't been touched yet -- the two sides of one pair legitimately
    # have different extensions during a gradual, file-by-file migration.
    _write(
        shared / "i18n-demo-partial" / "i18n-demo-partial.yml",
        "title: I18n demo section (partial)\n"
        "default_titles:\n"
        "  bonjour: Bonjour\n"
        "flavors:\n"
        "  - name: bonjour\n"
        "    includes:\n"
        "      - bonjour\n",
    )
    _write(shared / "i18n-demo-partial" / "bonjour.md", _heading("Bonjour"))
    _write(
        shared / "i18n-demo-partial" / "en" / "en.yml",
        "title: I18n demo section (partial, en)\n"
        "default_titles:\n"
        "  bonjour: Hello\n"
        "flavors:\n"
        "  - name: bonjour\n"
        "    includes:\n"
        "      - bonjour\n",
    )
    _write(shared / "i18n-demo-partial" / "en" / "bonjour.tex", _frame("Hello"))

    _write(
        tmp_path / "company" / "xyz" / "deck.yml",
        "name: XYZ\n"
        "parts:\n"
        "  - name: p1\n"
        "    title: Part 1\n"
        "    sections:\n"
        "      - $i18n-demo@hello\n"
        "      - $i18n-demo-legacy@goodbye\n"
        "      - $i18n-demo-partial@bonjour\n",
    )
    _write(
        tmp_path / "company" / "xyz" / "en" / "deck.yml",
        "name: XYZ\n"
        "parts:\n"
        "  - name: p1\n"
        "    title: Part 1\n"
        "    sections:\n"
        "      - $i18n-demo/en@hello\n"
        "      - $i18n-demo-legacy/en@goodbye\n"
        "      - $i18n-demo-partial/en@bonjour\n",
    )
    return tmp_path


def test_deck_pair_with_mixed_markdown_and_latex_content(repo: Path) -> None:
    settings = DeckSettings.from_yaml(repo / "company" / "xyz")
    pairings = {p.fr_path.name: p for p in deck_pair(settings)}

    hello = pairings["hello.md"]
    assert hello.included == "yes"
    assert hello.exists_on_disk
    assert hello.en_path == repo / "shared/latex/i18n-demo/en/hello.md"

    goodbye = pairings["goodbye.tex"]
    assert goodbye.included == "yes"
    assert goodbye.exists_on_disk
    assert goodbye.en_path == repo / "shared/latex/i18n-demo-legacy/en/goodbye.tex"

    # fr migrated to .md, en still .tex: en_counterpart must find the
    # existing .tex counterpart rather than predicting a nonexistent .md one.
    bonjour = pairings["bonjour.md"]
    assert bonjour.included == "yes"
    assert bonjour.exists_on_disk
    assert bonjour.en_path == repo / "shared/latex/i18n-demo-partial/en/bonjour.tex"


def test_section_files_with_markdown_content(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)
    files = section_files(
        settings.paths.shared_latex_dir,
        settings.file_extensions,
        "i18n-demo",
        FlavorName("hello"),
    )
    assert {p.name for p in files} == {"hello.md"}


def test_section_pair_clean_with_markdown_content(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)
    pairings = section_pair(
        settings.paths.shared_latex_dir,
        settings.file_extensions,
        "i18n-demo",
        FlavorName("hello"),
    )
    assert len(pairings) == 1
    assert pairings[0].included == "yes"
    assert pairings[0].exists_on_disk


def test_section_flavor_diff_clean_with_markdown_content(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)
    assert section_flavor_diff(settings.paths.shared_latex_dir, "i18n-demo") == []


def test_section_en_leak_clean_with_markdown_content(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)
    assert (
        section_en_leak(
            settings.paths.shared_latex_dir, settings.file_extensions, "i18n-demo"
        )
        == []
    )
