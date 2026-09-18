from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pytest import CaptureFixture, fixture

from deckz.cli import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")


def _frame(title: str) -> str:
    return f"\\begin{{frame}}{{{title}}}\n  {title}!\n\\end{{frame}}\n"


def run_deckz(*args: str) -> None:
    with patch("sys.argv", ["deckz", *args]):
        try:
            main()
        except SystemExit as e:
            if e.code != 0:
                raise e


@fixture
def working_dir(tmp_path: Path, monkeypatch: Any) -> Iterator[Path]:
    import appdirs
    from pygit2 import init_repository

    init_repository(str(tmp_path))
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_path))
    _write(tmp_path / "deckz.yml", 'build_command: ["true"]\n')

    shared = tmp_path / "shared" / "latex"
    # A single section definition, never duplicated for English: only the
    # translated body file lives under a sibling en/ directory.
    _write(
        shared / "i18n-demo" / "i18n-demo.yml",
        "title:\n"
        "  fr: Section de démo\n"
        "  en: Demo section\n"
        "flavors:\n"
        "  - name: hello\n"
        "    includes:\n"
        "      - hello\n",
    )
    _write(shared / "i18n-demo" / "hello.tex", _frame("Bonjour"))
    _write(shared / "i18n-demo" / "en" / "hello.tex", _frame("Hello"))

    deck_dir = tmp_path / "company" / "xyz"
    _write(
        deck_dir / "deck.yml",
        "name: XYZ\n"
        "parts:\n"
        "  - name: p1\n"
        "    title:\n"
        "      fr: Partie 1\n"
        "      en: Part 1\n"
        "    sections:\n"
        "      - $i18n-demo@hello\n",
    )
    monkeypatch.chdir(deck_dir)
    yield deck_dir


def test_show_paths(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    run_deckz("show", "paths")

    out = capsys.readouterr().out.splitlines()
    assert out == [str(working_dir.parent.parent / "shared/latex/i18n-demo/hello.tex")]


def test_section_flavors(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    run_deckz("section-flavors", "i18n-demo")

    assert capsys.readouterr().out.splitlines() == ["hello"]


def test_section_files(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    run_deckz("section-files", "i18n-demo", "hello")

    (line,) = capsys.readouterr().out.splitlines()
    assert line.endswith("i18n-demo/hello.tex")


def test_missing_en_clean(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    run_deckz("i18n", "missing-en")

    assert capsys.readouterr().out == ""


def test_missing_en_reports_missing_file(
    working_dir: Path, capsys: CaptureFixture[str]
) -> None:
    (working_dir.parent.parent / "shared/latex/i18n-demo/en/hello.tex").unlink()

    run_deckz("i18n", "missing-en")

    (line,) = capsys.readouterr().out.splitlines()
    assert line.startswith("FILE\t")
    assert line.endswith("i18n-demo/en/hello.tex")


def test_missing_en_reports_missing_translation_key(
    working_dir: Path, capsys: CaptureFixture[str]
) -> None:
    deck_path = working_dir / "deck.yml"
    deck_path.write_text(
        deck_path.read_text(encoding="utf8").replace("      en: Part 1\n", ""),
        encoding="utf8",
    )

    run_deckz("i18n", "missing-en")

    lines = capsys.readouterr().out.splitlines()
    assert any(
        line.startswith("TITLE\tmissing-en") and line.endswith("parts[p1].title")
        for line in lines
    )


def test_missing_en_reports_untranslated_plain_string(
    working_dir: Path, capsys: CaptureFixture[str]
) -> None:
    section_path = working_dir.parent.parent / "shared/latex/i18n-demo/i18n-demo.yml"
    section_path.write_text(
        section_path.read_text(encoding="utf8").replace(
            "title:\n  fr: Section de démo\n  en: Demo section\n",
            "title: Section de démo\n",
        ),
        encoding="utf8",
    )

    run_deckz("i18n", "missing-en")

    lines = capsys.readouterr().out.splitlines()
    assert any(
        line.startswith("TITLE\tuntranslated") and line.endswith("\ttitle")
        for line in lines
    )


def test_search_sections(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    run_deckz("search-sections", "bonjour")

    (line,) = capsys.readouterr().out.splitlines()
    assert line.startswith("FRAME i18n-demo\t")
    assert line.endswith("\tBonjour")
