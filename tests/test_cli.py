import json
import sys  # ruff: ignore[unused-import]
from pathlib import Path
from shutil import copytree, move
from typing import Any

import appdirs
from pdfminer.high_level import extract_pages, extract_text
from pydantic import ValidationError
from pygit2 import init_repository
from pytest import fixture, raises

from deckz.cli import main
from deckz.exceptions import DeckzError, FlavorAlreadyExistsError, FlavorNotFoundError


def _make_repo(tmp_path: Path, monkeypatch: Any) -> Path:
    data_dir = Path(__file__).parent / "test_cli"
    tmp_dir = tmp_path / "data"
    tmp_user_dir = tmp_path / "user"
    tmp_user_dir.mkdir()
    copytree(data_dir, tmp_dir)
    move(tmp_dir / "user-variables.yml", tmp_user_dir / "variables.yml")
    init_repository(str(tmp_dir))
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_dir))
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
    with pdf_path.open("rb") as fh:
        pages = list(extract_pages(fh))
        fh.seek(0)
        text = extract_text(fh)
    return len(pages), text


def test_generate_agent_notes(capsys: Any) -> None:
    main("generate-agent-notes")

    output = capsys.readouterr().out
    assert "deckz run file LATEX" in output
    assert "deckz run shared" in output


def test_extras_labs(tmp_path: Path) -> None:
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

    main(("extras", "labs", str(notebook_path)))

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


def test_run_decks(working_dir: Path) -> None:
    main(("run", "decks"))

    n_pages, text = extract_info(working_dir / "pdf" / "abc-p1-presentation.pdf")
    assert n_pages == 14
    assert "John Doe" in text


def test_run_shared(working_dir: Path) -> None:
    main(("run", "shared"))

    git_dir = working_dir.parent.parent
    pdf_path = git_dir / ".run" / "shared" / "pdf" / "shared-sections-presentation.pdf"
    _, text = extract_info(pdf_path)
    assert "Shared description content" in text
    assert "Extra shared content" in text


def test_run_all(working_dir: Path) -> None:
    main(("run", "all"))

    git_dir = working_dir.parent.parent
    pdf_path = git_dir / ".run" / "all" / "pdf" / "run-all-sections-presentation.pdf"
    _, text = extract_info(pdf_path)
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


def test_clean_latex_dry_run(working_dir: Path) -> None:
    shared_unused_path = working_dir.parent.parent / "latex" / "questions.tex"
    local_unused_path = working_dir / "latex" / "orphan.tex"
    assert shared_unused_path.exists()
    assert local_unused_path.exists()

    main(("clean", "latex", "--dry-run"))

    assert shared_unused_path.exists()
    assert local_unused_path.exists()


def test_clean_latex(working_dir: Path) -> None:
    shared_unused_path = working_dir.parent.parent / "latex" / "questions.tex"
    local_unused_path = working_dir / "latex" / "orphan.tex"
    used_path = working_dir / "latex" / "about.tex"
    assert shared_unused_path.exists()
    assert local_unused_path.exists()
    assert used_path.exists()

    main(("clean", "latex"))

    assert not shared_unused_path.exists()
    assert not local_unused_path.exists()
    assert used_path.exists()


def test_flavor_deduplicate_dry_run(working_dir: Path) -> None:
    section_path = working_dir / "latex" / "first-section" / "first-section.yml"
    deck_path = working_dir / "deck.yml"

    main(("flavor", "deduplicate", "--dry-run"))

    assert "name: light2" in section_path.read_text()
    assert "@light2" in deck_path.read_text()


def test_flavor_deduplicate(working_dir: Path) -> None:
    section_path = working_dir / "latex" / "first-section" / "first-section.yml"
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
    section_path = working_dir / "latex" / "first-section" / "first-section.yml"
    deck_path = working_dir / "deck.yml"

    main(("flavor", "rename", "first-section", "standard", "extended", "--dry-run"))

    assert "name: standard" in section_path.read_text()
    assert "@standard" in deck_path.read_text()


def test_flavor_rename(working_dir: Path) -> None:
    section_path = working_dir / "latex" / "first-section" / "first-section.yml"
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


def test_flavor_rename_unknown_flavor(working_dir: Path) -> None:
    with raises(FlavorNotFoundError):
        main(("flavor", "rename", "first-section", "nonexistent", "extended"))


def test_flavor_rename_name_collision(working_dir: Path) -> None:
    with raises(FlavorAlreadyExistsError):
        main(("flavor", "rename", "first-section", "standard", "light"))


def test_run_fr_default(bilingual_dir: Path) -> None:
    main(("run",))

    # The template fixture's \input loop doesn't actually pull frame bodies
    # in (a pre-existing quirk of this minimal test template, unrelated to
    # --en), so assert on what it does render: the deck title (a variables.yml
    # lang-map) and the section title (a deck.yml node-include lang-map).
    # File-level en/ sibling resolution itself is covered directly, at the
    # Parser level, in test_parser_lang.py.
    _, text = extract_info(bilingual_dir / "pdf" / "bilingual-p1-presentation.pdf")
    assert "Cas Bilingue" in text
    assert "Bonjour" in text
    assert "Bilingual Case" not in text
    assert "Hello" not in text


def test_run_en(bilingual_dir: Path) -> None:
    main(("run", "--en"))

    _, text = extract_info(
        bilingual_dir / "pdf" / "en" / "bilingual-p1-presentation.pdf"
    )
    assert "Bilingual Case" in text
    assert "Hello" in text
    assert "Cas Bilingue" not in text
    assert "Bonjour" not in text
    # fr output lives at its own, unsuffixed path -- --en never touches it.
    assert not (bilingual_dir / "pdf" / "bilingual-p1-presentation.pdf").exists()


def test_run_en_missing_file_fails_loudly(bilingual_dir: Path) -> None:
    (bilingual_dir / "latex" / "en" / "hello.tex").unlink()

    with raises(DeckzError):
        main(("run", "--en"))


def test_run_en_missing_title_translation_fails_loudly(bilingual_dir: Path) -> None:
    deck_path = bilingual_dir / "deck.yml"
    deck_path.write_text(
        deck_path.read_text(encoding="utf8").replace("      en: Part 1\n", ""),
        encoding="utf8",
    )

    with raises(ValidationError):
        main(("run", "--en"))


def test_run_en_plain_string_title_used_as_is(bilingual_dir: Path) -> None:
    """A plain string title means "the same in every language" -- not an error."""
    deck_path = bilingual_dir / "deck.yml"
    deck_path.write_text(
        deck_path.read_text(encoding="utf8").replace(
            "    title:\n      fr: Partie 1\n      en: Part 1\n", "    title: Neutre\n"
        ),
        encoding="utf8",
    )

    main(("run", "--en"))

    _, text = extract_info(
        bilingual_dir / "pdf" / "en" / "bilingual-p1-presentation.pdf"
    )
    assert "Bilingual Case" in text
