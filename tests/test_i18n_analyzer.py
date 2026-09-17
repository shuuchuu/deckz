from pathlib import Path
from typing import Any

from pytest import fixture

from deckz.analyzing.i18n_analyzer import (
    deck_pair,
    en_counterpart,
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


def _frame(title: str) -> str:
    return f"\\begin{{frame}}{{{title}}}\n  {title}!\n\\end{{frame}}\n"


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    import appdirs
    from pygit2 import init_repository

    init_repository(str(tmp_path))
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_path))
    _write(tmp_path / "deckz.yml", 'build_command: ["true"]\n')

    shared = tmp_path / "shared" / "latex"

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
    _write(shared / "i18n-demo" / "hello.tex", _frame("Bonjour"))
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
    _write(shared / "i18n-demo" / "en" / "hello.tex", _frame("Hello"))

    _write(
        shared / "i18n-demo-fr-only" / "i18n-demo-fr-only.yml",
        "title: Fr only section\n"
        "flavors:\n"
        "  - name: solo\n"
        "    includes:\n"
        "      - solo\n",
    )
    _write(shared / "i18n-demo-fr-only" / "solo.tex", _frame("Au revoir"))

    _write(
        shared / "i18n-leaky" / "i18n-leaky.yml",
        "title: Leaky section\n"
        "flavors:\n"
        "  - name: leaky\n"
        "    includes:\n"
        "      - local\n",
    )
    _write(shared / "i18n-leaky" / "local.tex", _frame("Local"))
    _write(
        shared / "i18n-leaky" / "en" / "en.yml",
        "title: Leaky section (en)\n"
        "flavors:\n"
        "  - name: leaky\n"
        "    includes:\n"
        # Absolute include forgetting its "/en" suffix: resolves straight to
        # the fr file instead of a translated one, exactly the real bug
        # section_en_leak exists to catch.
        "      - /i18n-demo/hello\n",
    )

    _write(shared / "footer.tex", _frame("Merci"))
    _write(shared / "en" / "footer.tex", _frame("Thanks"))

    _write(
        tmp_path / "company" / "xyz" / "deck.yml",
        "name: XYZ\n"
        "parts:\n"
        "  - name: p1\n"
        "    title: Part 1\n"
        "    sections:\n"
        "      - $i18n-demo@hello\n"
        "      - $i18n-demo-fr-only@solo\n"
        "      - footer\n",
    )
    _write(
        tmp_path / "company" / "xyz" / "en" / "deck.yml",
        "name: XYZ\n"
        "parts:\n"
        "  - name: p1\n"
        "    title: Part 1\n"
        "    sections:\n"
        "      - $i18n-demo/en@hello\n"
        "      - en/footer\n",
    )
    return tmp_path


def test_en_counterpart_nested_file() -> None:
    shared = Path("/repo/shared/latex")
    assert en_counterpart(shared / "python/basics/foo.tex", shared, shared) == (
        shared / "python/basics/en/foo.tex"
    )


def test_en_counterpart_shared_root_file() -> None:
    """Test a bare top-level shared file.

    e.g. contact.tex counterparts under a top-level en/ folder, not itself \
    unchanged.
    """
    shared = Path("/repo/shared/latex")
    assert en_counterpart(shared / "contact.tex", shared, shared) == (
        shared / "en" / "contact.tex"
    )


def test_en_counterpart_deck_local_root_file() -> None:
    """Test a deck-local root file.

    It needs no extra "en" segment: en_root is already the en-side latex root.
    """
    local = Path("/repo/deck/latex")
    en_root = Path("/repo/deck/en/latex")
    assert en_counterpart(local / "about.tex", local, en_root) == en_root / "about.tex"


def test_deck_pair(repo: Path) -> None:
    settings = DeckSettings.from_yaml(repo / "company" / "xyz")
    pairings = {p.fr_path.name: p for p in deck_pair(settings)}

    hello = pairings["hello.tex"]
    assert hello.included == "yes"
    assert hello.exists_on_disk
    assert hello.en_path is not None
    assert hello.en_path == repo / "shared/latex/i18n-demo/en/hello.tex"

    solo = pairings["solo.tex"]
    assert solo.included == "no"
    assert not solo.exists_on_disk

    footer = pairings["footer.tex"]
    assert footer.included == "yes"
    assert footer.en_path == repo / "shared/latex/en/footer.tex"


def test_section_flavor_diff_clean(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)
    assert section_flavor_diff(settings.paths.shared_latex_dir, "i18n-demo") == []


def test_section_flavor_diff_no_en_yml(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)
    findings = section_flavor_diff(settings.paths.shared_latex_dir, "i18n-demo-fr-only")
    assert any(f.startswith("NO_EN_YML") for f in findings)
    assert "MISSING_FLAVOR solo" in findings


def test_section_files(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)
    files = section_files(
        settings.paths.shared_latex_dir,
        settings.file_extension,
        "i18n-demo",
        FlavorName("hello"),
    )
    assert {p.name for p in files} == {"hello.tex"}


def test_section_pair_clean(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)
    pairings = section_pair(
        settings.paths.shared_latex_dir,
        settings.file_extension,
        "i18n-demo",
        FlavorName("hello"),
    )
    assert len(pairings) == 1
    assert pairings[0].included == "yes"
    assert pairings[0].exists_on_disk


def test_section_pair_no_en_yml(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)
    pairings = section_pair(
        settings.paths.shared_latex_dir,
        settings.file_extension,
        "i18n-demo-fr-only",
        FlavorName("solo"),
    )
    assert len(pairings) == 1
    assert pairings[0].included == "no-en-yml"
    assert not pairings[0].exists_on_disk


def test_section_en_leak_clean(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)
    assert (
        section_en_leak(
            settings.paths.shared_latex_dir, settings.file_extension, "i18n-demo"
        )
        == []
    )


def test_section_en_leak_no_en_yml(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)
    findings = section_en_leak(
        settings.paths.shared_latex_dir, settings.file_extension, "i18n-demo-fr-only"
    )
    assert len(findings) == 1
    assert findings[0].startswith("NO_EN_YML")


def test_section_en_leak_detects_leak(repo: Path) -> None:
    settings = GlobalSettings.from_yaml(repo)
    findings = section_en_leak(
        settings.paths.shared_latex_dir, settings.file_extension, "i18n-leaky"
    )
    assert len(findings) == 1
    assert findings[0].startswith("FLAVOR leaky LEAK")
    assert "i18n-demo/hello.tex" in findings[0]
