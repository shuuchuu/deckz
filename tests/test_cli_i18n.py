from collections.abc import Iterator
from json import loads
from pathlib import Path
from typing import Any

from pytest import CaptureFixture, fixture, raises

from deckz.cli import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")


def _frame(title: str) -> str:
    return f"# {title}\n\n{title}!\n"


@fixture
def working_dir(tmp_path: Path, monkeypatch: Any) -> Iterator[Path]:
    import appdirs
    from pygit2 import init_repository

    init_repository(str(tmp_path))
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_path))

    shared = tmp_path / "content"
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
    _write(shared / "i18n-demo" / "hello.md", _frame("Bonjour"))
    _write(shared / "i18n-demo" / "en" / "hello.md", _frame("Hello"))

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
    main(("show", "paths"))

    out = capsys.readouterr().out.splitlines()
    assert out == [str(working_dir.parent.parent / "content/i18n-demo/hello.md")]


def test_show_paths_en(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    main(("show", "paths", "--lang", "en"))

    out = capsys.readouterr().out.splitlines()
    assert out == [str(working_dir.parent.parent / "content/i18n-demo/en/hello.md")]


def test_show_tree_en_flags_missing_translation(working_dir: Path) -> None:
    (working_dir.parent.parent / "content/i18n-demo/en/hello.md").unlink()
    main(("show", "tree"))

    with raises(SystemExit) as exc_info:
        main(("show", "tree", "--lang", "en"))

    assert exc_info.value.code == 1


def test_show_variables_en(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    _write(working_dir / "variables.yml", "greeting:\n  fr: Bonjour\n  en: Hello\n")

    main(("show", "variables", "--lang", "en"))

    assert "Hello" in capsys.readouterr().out


def test_show_json(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    _write(working_dir / "variables.yml", "greeting:\n  fr: Bonjour\n  en: Hello\n")
    hello = str(working_dir.parent.parent / "content/i18n-demo/hello.md")

    main(("show", "paths", "--json"))
    assert loads(capsys.readouterr().out) == [hello]

    main(("show", "variables", "--lang", "en", "--json"))
    assert loads(capsys.readouterr().out)["greeting"] == "Hello"

    main(("show", "settings", "--json"))
    settings = loads(capsys.readouterr().out)
    assert settings["paths"]["current_dir"] == str(working_dir.resolve())

    assert "deck_definition" in settings["paths"]
    # Outside a deck, the repository's settings, without deck-only paths.
    main(("show", "settings", "--json", "--workdir", str(working_dir.parent)))
    settings = loads(capsys.readouterr().out)
    assert "deck_definition" not in settings["paths"]

    main(("show", "tree", "--json"))
    tree = loads(capsys.readouterr().out)
    (part,) = tree["parts"]
    (section,) = part["nodes"]
    assert (section["kind"], section["path"], section["error"]) == (
        "section",
        "i18n-demo",
        None,
    )
    (file,) = section["nodes"]
    assert file["resolved_path"] == hello


def test_section_flavors(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    main(("section-flavors", "i18n-demo"))

    assert capsys.readouterr().out.splitlines() == ["hello"]


def test_section_files(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    main(("section-files", "i18n-demo", "hello"))

    (line,) = capsys.readouterr().out.splitlines()
    assert line.endswith("i18n-demo/hello.md")


def test_section_files_en(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    main(("section-files", "i18n-demo", "hello", "--lang", "en"))

    (line,) = capsys.readouterr().out.splitlines()
    assert line.endswith("i18n-demo/en/hello.md")


def test_search_sections_en(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    main(("search-sections", "hello", "--lang", "en"))

    out = capsys.readouterr().out
    assert "SECTION" not in out
    assert "i18n-demo/en/hello.md\tHello" in out


def test_missing_en_clean(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    main(("i18n", "missing-en"))

    assert capsys.readouterr().out == ""


def test_missing_en_reports_missing_file(
    working_dir: Path, capsys: CaptureFixture[str]
) -> None:
    (working_dir.parent.parent / "content/i18n-demo/en/hello.md").unlink()

    with raises(SystemExit) as exc_info:
        main(("i18n", "missing-en"))

    assert exc_info.value.code == 1
    (line,) = capsys.readouterr().out.splitlines()
    assert line.startswith("FILE\t")
    assert line.endswith("i18n-demo/en/hello.md")


def test_missing_en_reports_missing_translation_key(
    working_dir: Path, capsys: CaptureFixture[str]
) -> None:
    deck_path = working_dir / "deck.yml"
    deck_path.write_text(
        deck_path.read_text(encoding="utf8").replace("      en: Part 1\n", ""),
        encoding="utf8",
    )

    with raises(SystemExit) as exc_info:
        main(("i18n", "missing-en"))

    assert exc_info.value.code == 1
    lines = capsys.readouterr().out.splitlines()
    assert any(
        line.startswith("TITLE\tmissing-en") and line.endswith("parts[p1].title")
        for line in lines
    )


def test_missing_en_reports_untranslated_plain_string(
    working_dir: Path, capsys: CaptureFixture[str]
) -> None:
    section_path = working_dir.parent.parent / "content/i18n-demo/i18n-demo.yml"
    section_path.write_text(
        section_path.read_text(encoding="utf8").replace(
            "title:\n  fr: Section de démo\n  en: Demo section\n",
            "title: Section de démo\n",
        ),
        encoding="utf8",
    )

    # Informational only: hidden by default, and never a failure.
    main(("i18n", "missing-en"))
    assert capsys.readouterr().out == ""

    main(("i18n", "missing-en", "--untranslated"))

    lines = capsys.readouterr().out.splitlines()
    assert any(
        line.startswith("TITLE\tuntranslated") and line.endswith("\ttitle")
        for line in lines
    )


def test_search_sections(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    main(("search-sections", "bonjour"))

    (line,) = capsys.readouterr().out.splitlines()
    assert line.startswith("FRAME fr i18n-demo\t")
    assert line.endswith("\tBonjour")


def test_search_sections_json(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    main(("search-sections", "bonjour", "--json"))

    (record,) = loads(capsys.readouterr().out)
    assert record["kind"] == "frame"
    assert record["lang"] == "fr"
    assert record["section"] == "i18n-demo"
    assert record["title"] == "Bonjour"


def test_search_sections_in_both_langs(
    working_dir: Path, capsys: CaptureFixture[str]
) -> None:
    main(("search-sections", "bonjour", "hello", "--lang", "fr", "en", "--json"))

    records = loads(capsys.readouterr().out)
    assert {(record["lang"], record["title"]) for record in records} == {
        ("fr", "Bonjour"),
        ("en", "Hello"),
    }


def test_missing_en_json(working_dir: Path, capsys: CaptureFixture[str]) -> None:
    (working_dir.parent.parent / "content/i18n-demo/en/hello.md").unlink()

    with raises(SystemExit):
        main(("i18n", "missing-en", "--json"))

    (record,) = loads(capsys.readouterr().out)
    assert record["kind"] == "file"
    assert record["en_path"].endswith("i18n-demo/en/hello.md")
