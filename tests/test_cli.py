import json
import sys  # ruff: ignore[unused-import]
from json import loads
from pathlib import Path
from shutil import copytree, move
from typing import Any

import appdirs
from pygit2 import init_repository
from pypdfium2 import PdfDocument
from pytest import fixture, raises

from deckz.checking import preview_settings
from deckz.cli import main
from deckz.configuring.settings import DeckSettings


def _make_repo(tmp_path: Path, monkeypatch: Any) -> Path:
    data_dir = Path(__file__).parent / "test_cli"
    tmp_dir = tmp_path / "data"
    tmp_user_dir = tmp_path / "user"
    tmp_user_dir.mkdir()
    copytree(data_dir, tmp_dir)
    move(tmp_dir / "user-variables.yml", tmp_user_dir / "variables.yml")
    init_repository(str(tmp_dir))
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_user_dir))
    return tmp_dir


@fixture
def working_dir(tmp_path: Path, monkeypatch: Any) -> Path:
    working_dir = _make_repo(tmp_path, monkeypatch) / "company" / "abc"
    monkeypatch.chdir(working_dir)
    return working_dir


@fixture
def bilingual_dir(tmp_path: Path, monkeypatch: Any) -> Path:
    working_dir = _make_repo(tmp_path, monkeypatch) / "company" / "bilingual"
    monkeypatch.chdir(working_dir)
    return working_dir


def extract_info(pdf_path: Path) -> tuple[int, str]:
    pdf = PdfDocument(pdf_path)
    try:
        return len(pdf), "\n".join(
            page.get_textpage().get_text_bounded() for page in pdf
        )
    finally:
        pdf.close()


def test_generate_agent_notes(capsys: Any) -> None:
    main("generate-agent-notes")

    output = capsys.readouterr().out
    assert "deckz run file PATH" in output
    assert "deckz run shared" in output


def test_labs_normalize(tmp_path: Path) -> None:
    init_repository(str(tmp_path))
    notebook_path = tmp_path / "demo.ipynb"
    notebook = {
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": ["# Solution\n"]}
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    notebook_path.write_text(json.dumps(notebook))

    main(("labs", "normalize", str(notebook_path), "--workdir", str(tmp_path)))

    written = json.loads(notebook_path.read_text())
    colab = written["metadata"]["colab"]
    assert colab["generative_ai_disabled"] is True
    assert len(colab["collapsed_sections"]) == 1


def test_run(working_dir: Path) -> None:
    main(("run", "--parts", "p1", "--parts", "p2"))

    n_pages, text = extract_info(working_dir / "pdf" / "abc-p1-presentation.pdf")
    assert n_pages == 14
    assert "John Doe" in text


def test_run_file(working_dir: Path) -> None:
    main(("run", "file", "about", "--no-open"))

    git_dir = working_dir.parent.parent
    pdf_path = (
        git_dir / ".run" / "file" / "about" / "pdf" / "deck-part_name-presentation.pdf"
    )
    n_pages, text = extract_info(pdf_path)
    assert n_pages == 3
    assert "John Doe" in text


def test_run_section(working_dir: Path) -> None:
    main(("run", "section", "first-section", "standard", "--no-open"))

    git_dir = working_dir.parent.parent
    pdf_path = (
        git_dir
        / ".run"
        / "section"
        / "first-section"
        / "standard"
        / "pdf"
        / "deck-part_name-presentation.pdf"
    )
    n_pages, text = extract_info(pdf_path)
    assert n_pages > 1
    assert "First section" in text


_HTML_ONLY = ("--html", "--no-handout", "--no-presentation", "--no-print")


def test_run_html(working_dir: Path, capsys: Any) -> None:
    main(("run", *_HTML_ONLY, "--dry-run"))
    assert capsys.readouterr().out.startswith("company/abc/html/abc-html: render all ")

    main(("run", *_HTML_ONLY))

    site = working_dir / "html" / "abc-html"
    index = (site / "index.html").read_text(encoding="utf8")
    assert "<h1>A Bold Case</h1>" in index
    # Fragments converted by `html_pandoc_command`, inlined by `fragment`.
    assert "<h1>Introduction</h1>" in index
    assert "Would it save you a lot of time" in index
    assert (site / "img" / "logo.png").is_file()
    assert not (working_dir / "pdf").exists()


def test_run_html_needs_its_pandoc_command(working_dir: Path) -> None:
    deckz_yml = working_dir.parent.parent / "deckz.yml"
    config = deckz_yml.read_text(encoding="utf8")
    deckz_yml.write_text(config[: config.index("# `--html` builds")], encoding="utf8")

    with raises(SystemExit) as exc_info:
        main(("run", *_HTML_ONLY))

    assert exc_info.value.code == 1


def test_run_file_html(working_dir: Path) -> None:
    main(("run", "file", "about", *_HTML_ONLY, "--no-open"))

    git_dir = working_dir.parent.parent
    index = git_dir / ".run" / "file" / "about" / "html" / "deck-html" / "index.html"
    assert "A Bold Case" in index.read_text(encoding="utf8")


def test_run_decks(working_dir: Path) -> None:
    main(("run", "decks"))

    n_pages, text = extract_info(working_dir / "pdf" / "abc-p1-presentation.pdf")
    assert n_pages == 14
    assert "John Doe" in text


def _all_pdfs_text(pdf_dir: Path) -> str:
    # One PDF per shared section (see deckz.checking).
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    assert pdfs
    return "\n".join(extract_info(pdf)[1] for pdf in pdfs)


def test_run_shared(working_dir: Path) -> None:
    main(("run", "shared"))

    git_dir = working_dir.parent.parent
    text = _all_pdfs_text(git_dir / ".run" / "shared" / "pdf")
    assert "Shared description content" in text
    assert "Extra shared content" in text


def test_run_all(working_dir: Path) -> None:
    main(("run", "all"))

    git_dir = working_dir.parent.parent
    text = _all_pdfs_text(git_dir / ".run" / "all" / "pdf")
    assert "Shared description content" in text
    assert "ABC-local override of the shared description" in text
    assert text.count("Extra shared content") == 2


def test_clean_all_removes_run_shared_and_all_scratch_dirs(
    working_dir: Path,
) -> None:
    main(("run", "shared"))
    main(("run", "all"))

    git_dir = working_dir.parent.parent
    shared_scratch_dir = git_dir / ".run" / "shared"
    all_scratch_dir = git_dir / ".run" / "all"
    assert shared_scratch_dir.is_dir()
    assert all_scratch_dir.is_dir()

    main(("clean", "all"))

    assert not shared_scratch_dir.exists()
    assert not all_scratch_dir.exists()


def test_clean_all_removes_run_scratch_dir(working_dir: Path) -> None:
    main(("run", "file", "about", "--no-open"))

    git_dir = working_dir.parent.parent
    run_scratch_dir = git_dir / ".run"
    assert run_scratch_dir.is_dir()

    main(("clean", "all"))

    assert not run_scratch_dir.exists()


def test_clean_content_dry_run(working_dir: Path) -> None:
    shared_unused_path = working_dir.parent.parent / "content" / "questions.md"
    local_unused_path = working_dir / "content" / "orphan.md"
    assert shared_unused_path.exists()
    assert local_unused_path.exists()

    main(("clean", "content", "--dry-run"))

    assert shared_unused_path.exists()
    assert local_unused_path.exists()


def test_clean_content(working_dir: Path) -> None:
    shared_unused_path = working_dir.parent.parent / "content" / "questions.md"
    local_unused_path = working_dir / "content" / "orphan.md"
    used_path = working_dir / "content" / "about.md"
    assert shared_unused_path.exists()
    assert local_unused_path.exists()
    assert used_path.exists()

    main(("clean", "content"))

    assert not shared_unused_path.exists()
    assert not local_unused_path.exists()
    assert used_path.exists()


def test_clean_content_keeps_en_translations(bilingual_dir: Path) -> None:
    shared_content_dir = bilingual_dir.parent.parent / "content"
    (shared_content_dir / "en").mkdir()
    local_en_path = bilingual_dir / "content" / "en" / "hello.md"
    # Under --en, a deck's local en/ file wins over the shared one...
    shadowed_en_path = shared_content_dir / "en" / "hello.md"
    shadowed_en_path.write_text("Hello\n", encoding="utf8")
    # ...and over a shared fr file...
    local_en_over_shared_fr_path = bilingual_dir / "content" / "en" / "questions.md"
    local_en_over_shared_fr_path.write_text("Questions?\n", encoding="utf8")
    # ...while a local fr file with no local en/ one falls back to the shared en/.
    (bilingual_dir / "content" / "bye.md").write_text("Au revoir\n", encoding="utf8")
    shared_fallback_en_path = shared_content_dir / "en" / "bye.md"
    shared_fallback_en_path.write_text("Bye\n", encoding="utf8")
    orphan_en_path = bilingual_dir / "content" / "en" / "orphan.md"
    orphan_en_path.write_text("Orphan\n", encoding="utf8")
    deck_path = bilingual_dir / "deck.yml"
    deck_path.write_text(
        deck_path.read_text(encoding="utf8") + "      - questions\n      - bye\n",
        encoding="utf8",
    )

    main(("clean", "content"))

    assert local_en_path.exists()
    assert local_en_over_shared_fr_path.exists()
    assert shared_fallback_en_path.exists()
    assert not shadowed_en_path.exists()
    assert not orphan_en_path.exists()


def _use_logo_in_en_only(bilingual_dir: Path) -> Path:
    en_path = bilingual_dir / "content" / "en" / "hello.md"
    en_path.write_text(
        'Hello {{ assets_metadata_retriever("img/logo") }}\n', encoding="utf8"
    )
    return en_path


def test_asset_search_finds_en_files(bilingual_dir: Path, capsys: Any) -> None:
    _use_logo_in_en_only(bilingual_dir)

    main(("asset", "search", "img/logo"))

    assert "company/bilingual/content/en/hello.md" in capsys.readouterr().out


def test_asset_deps_finds_en_only_assets(bilingual_dir: Path, capsys: Any) -> None:
    _use_logo_in_en_only(bilingual_dir)

    main(("asset", "deps"))

    assert "img/logo.png" in capsys.readouterr().out


def test_asset_json(bilingual_dir: Path, capsys: Any) -> None:
    _use_logo_in_en_only(bilingual_dir)

    main(("asset", "search", "img/logo", "--json"))
    assert loads(capsys.readouterr().out) == ["company/bilingual/content/en/hello.md"]

    main(("asset", "deps", "--json"))
    assert any("img/logo" in r["assets"] for r in loads(capsys.readouterr().out))


def test_deps_json(working_dir: Path, capsys: Any) -> None:
    main(("deps", "--json"))
    assert loads(capsys.readouterr().out) == {"unused_flavors": {"about": ["standard"]}}

    deck_path = working_dir / "deck.yml"
    deck_path.write_text(
        deck_path.read_text(encoding="utf8").replace(
            "      - about\n", "      - $about@standard\n"
        ),
        encoding="utf8",
    )
    main(("deps", "about", "--json"))
    assert loads(capsys.readouterr().out) == {
        "unused_flavors": {},
        "dependents": {"company/abc": ["p2"]},
    }


def test_flavor_deduplicate_dry_run(working_dir: Path) -> None:
    section_path = working_dir / "content" / "first-section" / "first-section.yml"
    deck_path = working_dir / "deck.yml"

    main(("flavor", "deduplicate", "--dry-run"))

    assert "name: light2" in section_path.read_text()
    assert "@light2" in deck_path.read_text()


def test_flavor_deduplicate(working_dir: Path) -> None:
    section_path = working_dir / "content" / "first-section" / "first-section.yml"
    deck_path = working_dir / "deck.yml"

    main(("flavor", "deduplicate"))

    assert "name: light2" not in section_path.read_text()
    assert "@light2" not in deck_path.read_text()
    assert "$first-section@light" in deck_path.read_text()

    main(("run", "--parts", "p1", "--parts", "p2"))
    n_pages, text = extract_info(working_dir / "pdf" / "abc-p1-presentation.pdf")
    assert n_pages == 14
    assert "John Doe" in text


def test_flavor_rename_dry_run(working_dir: Path) -> None:
    section_path = working_dir / "content" / "first-section" / "first-section.yml"
    deck_path = working_dir / "deck.yml"

    main(("flavor", "rename", "first-section", "standard", "extended", "--dry-run"))

    assert "name: standard" in section_path.read_text()
    assert "@standard" in deck_path.read_text()


def test_flavor_rename(working_dir: Path) -> None:
    section_path = working_dir / "content" / "first-section" / "first-section.yml"
    deck_path = working_dir / "deck.yml"

    main(("flavor", "rename", "first-section", "standard", "extended"))

    assert "name: standard" not in section_path.read_text()
    assert "name: extended" in section_path.read_text()
    assert "@standard" not in deck_path.read_text()
    assert "$first-section@extended" in deck_path.read_text()

    main(("run", "--parts", "p1", "--parts", "p2"))
    n_pages, text = extract_info(working_dir / "pdf" / "abc-p1-presentation.pdf")
    assert n_pages == 14
    assert "John Doe" in text


def test_flavor_rename_unknown_flavor(working_dir: Path, caplog: Any) -> None:
    with raises(SystemExit) as exc_info:
        main(("flavor", "rename", "first-section", "nonexistent", "extended"))

    assert exc_info.value.code == 1
    assert "has no flavor named nonexistent" in caplog.text


def test_flavor_rename_name_collision(working_dir: Path, caplog: Any) -> None:
    with raises(SystemExit) as exc_info:
        main(("flavor", "rename", "first-section", "standard", "light"))

    assert exc_info.value.code == 1
    assert "already has a flavor named light" in caplog.text


def test_run_fr_default(bilingual_dir: Path) -> None:
    main(("run",))

    _, text = extract_info(bilingual_dir / "pdf" / "bilingual-p1-presentation.pdf")
    assert "Cas Bilingue" in text
    assert "Bonjour tout le monde!" in text
    assert "Bilingual Case" not in text
    assert "Hello" not in text


def test_run_en(bilingual_dir: Path) -> None:
    main(("run", "--lang", "en"))

    _, text = extract_info(
        bilingual_dir / "pdf" / "en" / "bilingual-p1-presentation.pdf"
    )
    assert "Bilingual Case" in text
    assert "Hello everyone!" in text
    assert "Cas Bilingue" not in text
    assert "Bonjour" not in text
    # fr output lives at its own, unsuffixed path -- --lang en never touches it.
    assert not (bilingual_dir / "pdf" / "bilingual-p1-presentation.pdf").exists()


def test_run_fr_and_en_in_one_pass(bilingual_dir: Path) -> None:
    main(("run", "--lang", "fr", "en", "--no-handout", "--no-print"))

    _, fr_text = extract_info(bilingual_dir / "pdf" / "bilingual-p1-presentation.pdf")
    _, en_text = extract_info(
        bilingual_dir / "pdf" / "en" / "bilingual-p1-presentation.pdf"
    )
    assert "Bonjour tout le monde!" in fr_text
    assert "Hello everyone!" in en_text


def _planned_pdfs(capsys: Any) -> set[str]:
    return {
        line.split(":")[0]
        for line in capsys.readouterr().out.splitlines()
        if not line.startswith(" ")
    }


def test_run_defaults_come_from_the_environment(
    bilingual_dir: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setenv("DECKZ_LANG", "fr en")
    monkeypatch.setenv("DECKZ_RUN_PRESENTATION", "false")
    monkeypatch.setenv("DECKZ_RUN_PRINT", "false")

    main(("run", "--dry-run"))

    # The whole deck's handout, and its single part's.
    assert _planned_pdfs(capsys) == {
        "company/bilingual/pdf/bilingual-handout.pdf",
        "company/bilingual/pdf/bilingual-p1-handout.pdf",
        "company/bilingual/pdf/en/bilingual-handout.pdf",
        "company/bilingual/pdf/en/bilingual-p1-handout.pdf",
    }


def test_run_options_override_the_environment(
    bilingual_dir: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setenv("DECKZ_LANG", "fr en")
    monkeypatch.setenv("DECKZ_RUN_PRESENTATION", "false")
    monkeypatch.setenv("DECKZ_RUN_HANDOUT", "false")
    monkeypatch.setenv("DECKZ_RUN_PRINT", "false")

    main(("run", "deck", "--lang", "en", "--presentation", "--dry-run"))

    assert _planned_pdfs(capsys) == {
        "company/bilingual/pdf/en/bilingual-p1-presentation.pdf"
    }


def test_run_defaults_come_from_a_dotenv_file(
    bilingual_dir: Path, monkeypatch: Any, capsys: Any
) -> None:
    from dotenv import main as dotenv_main

    # conftest stubs the lookup out: restore it for this test only.
    monkeypatch.setattr("dotenv.find_dotenv", dotenv_main.find_dotenv)
    # Registers the variables with monkeypatch, so that it unsets the ones
    # load_dotenv sets once the test is done.
    for name in ("DECKZ_LANG", "DECKZ_RUN_HANDOUT", "DECKZ_RUN_PRINT"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    (bilingual_dir.parent.parent / ".env").write_text(
        'DECKZ_LANG="en"\nDECKZ_RUN_HANDOUT=false\nDECKZ_RUN_PRINT=false\n',
        encoding="utf8",
    )

    main(("run", "--dry-run"))

    assert _planned_pdfs(capsys) == {
        "company/bilingual/pdf/en/bilingual-p1-presentation.pdf"
    }


def test_single_view_commands_ignore_deckz_lang(
    bilingual_dir: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setenv("DECKZ_LANG", "en")

    main(("show", "paths"))

    assert "/en/" not in capsys.readouterr().out


def test_run_en_missing_file_fails_loudly(
    bilingual_dir: Path, caplog: Any, capsys: Any
) -> None:
    (bilingual_dir / "content" / "en" / "hello.md").unlink()

    with raises(SystemExit) as exc_info:
        main(("run", "--lang", "en"))

    assert exc_info.value.code == 1
    assert "deck parsing failed" in caplog.text
    assert "hello" in capsys.readouterr().err


def test_run_en_missing_title_translation_fails_loudly(
    bilingual_dir: Path, caplog: Any
) -> None:
    deck_path = bilingual_dir / "deck.yml"
    deck_path.write_text(
        deck_path.read_text(encoding="utf8").replace("      en: Part 1\n", ""),
        encoding="utf8",
    )

    with raises(SystemExit) as exc_info:
        main(("run", "--lang", "en"))

    assert exc_info.value.code == 1
    assert "is not a valid deck definition" in caplog.text
    assert "missing 'en'" in caplog.text


def test_run_with_unparsable_deck_definition_exits_1(
    working_dir: Path, caplog: Any
) -> None:
    (working_dir / "deck.yml").write_text("name: [unclosed\n", encoding="utf8")

    with raises(SystemExit) as exc_info:
        main(("run",))

    assert exc_info.value.code == 1
    assert "is not valid YAML" in caplog.text


def test_run_outside_a_deck_exits_1(working_dir: Path, caplog: Any) -> None:
    with raises(SystemExit) as exc_info:
        main(("run", "--workdir", str(working_dir.parent)))

    assert exc_info.value.code == 1
    assert "no deck definition found" in caplog.text


def test_run_with_invalid_settings_exits_1(working_dir: Path, caplog: Any) -> None:
    (working_dir / "deckz.yml").write_text(
        "typst_parallel_compilations: 0\n", encoding="utf8"
    )

    with raises(SystemExit) as exc_info:
        main(("run",))

    assert exc_info.value.code == 1
    assert "invalid deckz.yml settings" in caplog.text


def test_run_en_plain_string_title_used_as_is(bilingual_dir: Path) -> None:
    """A plain string title means "the same in every language" -- not an error."""
    deck_path = bilingual_dir / "deck.yml"
    deck_path.write_text(
        deck_path.read_text(encoding="utf8").replace(
            "    title:\n      fr: Partie 1\n      en: Part 1\n", "    title: Neutre\n"
        ),
        encoding="utf8",
    )

    main(("run", "--lang", "en"))

    _, text = extract_info(
        bilingual_dir / "pdf" / "en" / "bilingual-p1-presentation.pdf"
    )
    assert "Bilingual Case" in text


def test_preview_settings_leaves_the_deck_settings_untouched(
    working_dir: Path,
) -> None:
    settings = DeckSettings.from_yaml(working_dir)
    pdf_dir = settings.paths.pdf_dir

    preview = preview_settings(settings, "section", "first-section", "standard")

    assert settings.paths.pdf_dir == pdf_dir
    scratch_dir = settings.paths.git_dir / ".run" / "section" / "first-section"
    assert preview.paths.pdf_dir == scratch_dir / "standard" / "pdf"
    assert preview.paths.build_dir == scratch_dir / "standard" / ".build"
    assert preview.paths.current_dir == settings.paths.current_dir
